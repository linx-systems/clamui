use serde_json::{json, Value};
use std::{fs, path::Path, time::Instant};

use crate::{
    common::{atomic_write, expand_path, sanitize_line},
    dispatch,
    headless::HeadlessContext,
    i18n, Context,
};

macro_rules! tr {
    ($message:literal) => {
        $message
    };
}
/// Returns whether arguments select the headless CLI route. `args` excludes argv0.
pub fn is_cli(args: &[String]) -> bool {
    matches!(
        args.first().map(String::as_str),
        Some(
            "scan"
                | "quarantine"
                | "profile"
                | "status"
                | "history"
                | "help"
                | "install-privileged-helper"
                | "--help"
                | "-h"
                | "--version"
                | "-V"
        )
    )
}

/// Runs the ClamUI headless CLI. `args` excludes argv0.
pub fn run(args: &[String]) -> i32 {
    match args.first().map(String::as_str) {
        None | Some("--help") | Some("-h") => root_help(),
        Some("--version") | Some("-V") => {
            println!("clamui {}", env!("CARGO_PKG_VERSION"));
            0
        }
        Some("help") => run_help(&args[1..]),
        Some("scan") => with_interrupt_context(|ctx| run_scan(ctx, &args[1..])),
        Some("quarantine") => with_context(|ctx| run_quarantine(ctx, &args[1..])),
        Some("profile") => with_context(|ctx| run_profile(ctx, &args[1..])),
        Some("status") => with_context(|ctx| run_status(ctx, &args[1..])),
        Some("history") => with_context(|ctx| run_history(ctx, &args[1..])),
        Some("install-privileged-helper") => {
            with_context(|ctx| run_install_privileged_helper(ctx, &args[1..]))
        }
        Some(command) => with_context(|ctx| {
            eprintln!(
                "{}: {}",
                tr(Some(ctx), "error"),
                trf(
                    Some(ctx),
                    "Unknown command: {command}",
                    &[("{command}", command)]
                )
            );
            print_root_help(Some(ctx));
            2
        }),
    }
}

/// Prints root CLI help without initializing a GUI runtime.
pub fn root_help() -> i32 {
    match Context::new() {
        Ok(ctx) => print_root_help(Some(&ctx)),
        Err(_) => print_root_help(None),
    }
    0
}

fn with_context(run_command: impl FnOnce(&Context) -> i32) -> i32 {
    match Context::new() {
        Ok(ctx) => run_command(&ctx),
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

fn with_interrupt_context(run_command: impl FnOnce(&Context) -> i32) -> i32 {
    match HeadlessContext::new() {
        Ok(headless) => run_command(headless.context()),
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

fn tr(ctx: Option<&Context>, message: &str) -> String {
    ctx.map_or_else(|| message.to_owned(), |ctx| i18n::translate(ctx, message))
}

fn trn(ctx: Option<&Context>, singular: &str, plural: &str, count: u64) -> String {
    ctx.map_or_else(
        || {
            if count == 1 {
                singular.to_owned()
            } else {
                plural.to_owned()
            }
        },
        |ctx| i18n::translate_plural(ctx, singular, plural, count),
    )
}

fn trf(ctx: Option<&Context>, message: &str, replacements: &[(&str, &str)]) -> String {
    let mut rendered = tr(ctx, message);
    for (placeholder, value) in replacements {
        rendered = rendered.replace(placeholder, value);
    }
    rendered
}

fn trnf(
    ctx: Option<&Context>,
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

fn print_root_help(ctx: Option<&Context>) {
    println!(
        "{}",
        tr(
            ctx,
            // Translators: The em dash separates the application name from its description.
            "ClamUI — ClamAV antivirus management\n",
        )
    );
    println!("{}", tr(ctx, "Usage:"));
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep `clamui` unchanged; it is the command name.
            "  clamui                   Launch the graphical interface"
        )
    );
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep `clamui`, `<command>`, and `[args]` unchanged; they are command syntax.
            "  clamui <command> [args]   Run a CLI command\n"
        )
    );
    println!("{}", tr(ctx, "Commands:"));
    for (name, summary) in command_summaries() {
        println!("  {name:<27} {}", tr(ctx, summary));
    }
    println!("{}", tr(ctx, "\nGlobal options:"));
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep `--json` and `JSON` unchanged; they are a CLI flag and data format.
            "  --json                   Machine-readable JSON output"
        )
    );
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep `-v` and `--verbose` unchanged; they are CLI flags.
            "  -v, --verbose            Verbose output",
        )
    );
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep `-h` and `--help` unchanged; they are CLI flags.
            "  -h, --help               Show help for any command\n"
        )
    );
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep the quoted `clamui help <command>` command unchanged.
            "Run 'clamui help <command>' for usage examples.",
        )
    );
    println!(
        "{}",
        tr(
            ctx,
            // Translators: Keep the quoted `clamui` command unchanged.
            "Run 'clamui' without arguments to launch the GUI.",
        )
    );
}

fn command_summaries() -> [(&'static str, &'static str); 7] {
    [
        ("scan", tr!("Scan files or directories for threats")),
        ("quarantine", tr!("Manage quarantined files")),
        ("profile", tr!("Manage scan profiles")),
        ("status", tr!("Show ClamAV and ClamUI status")),
        ("history", tr!("View scan history")),
        (
            "install-privileged-helper",
            tr!("Install the polkit helper for saving system ClamAV configs (native host only)"),
        ),
        ("help", tr!("Show this help message")),
    ]
}

fn run_help(args: &[String]) -> i32 {
    let Ok(ctx) = Context::new() else {
        return root_help();
    };
    if has_help(args) {
        println!(
            "{}",
            tr(
                Some(&ctx),
                // Translators: Keep `clamui` and `[COMMAND]` command syntax unchanged; translate the `Usage:` label.
                "Usage: clamui help [COMMAND]",
            )
        );
        println!(
            "{}",
            tr(
                Some(&ctx),
                "Display an overview of all commands or detailed help for a specific one."
            )
        );
        return 0;
    }
    if args.len() > 1 {
        eprintln!(
            "{}: {}",
            tr(Some(&ctx), "error"),
            tr(
                Some(&ctx),
                // Translators: Keep `help` unchanged; it is the literal CLI subcommand.
                "help accepts at most one command",
            )
        );
        return 2;
    }
    let Some(topic) = args.first() else {
        print_root_help(Some(&ctx));
        return 0;
    };
    let Some((_, summary)) = command_summaries()
        .into_iter()
        .find(|(name, _)| *name == topic.as_str())
    else {
        eprintln!(
            "{}",
            trf(
                Some(&ctx),
                "Unknown command: {name}\n",
                &[("{name}", topic.as_str())]
            )
        );
        print_root_help(Some(&ctx));
        return 1;
    };
    let translated_summary = tr(Some(&ctx), summary);
    println!(
        "{}",
        trf(
            Some(&ctx),
            // Translators: Keep `{name}` as the command name and `{summary}` as its translated description; the em dash separates them.
            "clamui {name} — {summary}\n",
            &[
                ("{name}", topic.as_str()),
                ("{summary}", translated_summary.as_str()),
            ]
        )
    );
    println!("{}", tr(Some(&ctx), "Examples:"));
    for example in command_examples(topic) {
        println!("  $ {example}");
    }
    println!(
        "{}",
        trf(
            Some(&ctx),
            // Translators: Keep the quoted `clamui {name} --help` command unchanged; preserve `{name}` as the command name.
            "\nRun 'clamui {name} --help' for full option reference.",
            &[("{name}", topic.as_str())]
        )
    );
    0
}

fn command_examples(topic: &str) -> &'static [&'static str] {
    match topic {
        "scan" => &[
            "clamui scan /home/user/Downloads",
            "clamui scan /tmp --quarantine --json",
            "clamui scan . --profile \"Quick Scan\" -v",
            "clamui scan file1.txt dir/ --no-recursive",
        ],
        "quarantine" => &[
            "clamui quarantine list",
            "clamui quarantine list --json",
            "clamui quarantine restore 42",
            "clamui quarantine delete 42",
        ],
        "profile" => &[
            "clamui profile list",
            "clamui profile show \"Full Scan\"",
            "clamui profile export \"Quick Scan\" backup.json",
            "clamui profile import backup.json",
        ],
        "status" => &["clamui status", "clamui status --json"],
        "history" => &[
            "clamui history",
            "clamui history --limit 50",
            "clamui history --type scan --json",
        ],
        "install-privileged-helper" => &["sudo clamui install-privileged-helper"],
        "help" => &["clamui help", "clamui help scan"],
        _ => &[],
    }
}

fn run_scan(ctx: &Context, args: &[String]) -> i32 {
    if has_help(args) {
        return print_scan_help(ctx);
    }

    let mut paths = Vec::new();
    let mut recursive = true;
    let mut profile_name = None;
    let mut quarantine = false;
    let mut json_output = false;
    let mut verbose = false;
    let mut options = true;
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        if options && arg == "--" {
            options = false;
        } else if options && arg == "--no-recursive" {
            recursive = false;
        } else if options && arg == "--quarantine" {
            quarantine = true;
        } else if options && arg == "--json" {
            json_output = true;
        } else if options && arg == "--verbose" {
            verbose = true;
        } else if options && arg == "--profile" {
            index += 1;
            let Some(value) = args.get(index) else {
                return argument_error(ctx, "--profile requires NAME");
            };
            profile_name = Some(value.clone());
        } else if options && arg.starts_with("--profile=") {
            profile_name = Some(arg["--profile=".len()..].to_owned());
        } else if options && arg.starts_with('-') && arg != "-" {
            let short = &arg.as_bytes()[1..];
            let mut short_index = 0;
            while short_index < short.len() {
                match short[short_index] {
                    b'v' => verbose = true,
                    b'q' => quarantine = true,
                    b'h' => return print_scan_help(ctx),
                    b'p' => {
                        if short_index + 1 < short.len() {
                            profile_name = Some(arg[short_index + 2..].to_owned());
                        } else {
                            index += 1;
                            let Some(value) = args.get(index) else {
                                return argument_error(ctx, "--profile requires NAME");
                            };
                            profile_name = Some(value.clone());
                        }
                        break;
                    }
                    _ => {
                        return argument_error(
                            ctx,
                            &trf(
                                Some(ctx),
                                "unrecognized argument: {argument}",
                                &[("{argument}", arg)],
                            ),
                        )
                    }
                }
                short_index += 1;
            }
        } else {
            paths.push(arg.clone());
        }
        index += 1;
    }
    if paths.is_empty() {
        return argument_error(ctx, "the following arguments are required: PATH");
    }

    let valid_paths = validate_scan_paths(ctx, &paths);
    if valid_paths.is_empty() {
        eprintln!(
            "{}: {}",
            tr(Some(ctx), "error"),
            tr(Some(ctx), "No valid paths to scan")
        );
        return 2;
    }

    let availability = match dispatch(ctx, "scanner.status", json!({})) {
        Ok(status) => status,
        Err(error) => {
            eprintln!("{}: {error}", tr(Some(ctx), "error"));
            return 2;
        }
    };
    if !availability["available"].as_bool().unwrap_or(false) {
        let error = availability["error"].as_str().unwrap_or_default();
        eprintln!(
            "error: {}",
            trf(
                Some(ctx),
                "ClamAV not available: {error}",
                &[("{error}", error)]
            )
        );
        return 2;
    }
    if verbose {
        let version = availability["version"].as_str().unwrap_or_default();
        eprintln!(
            "{}",
            trf(
                Some(ctx),
                "ClamAV version: {version}",
                &[("{version}", version)]
            )
        );
    }

    let profile = match profile_name {
        Some(name) => match find_profile(ctx, &name) {
            Ok(profile) => Some(profile),
            Err(message) => {
                eprintln!("{}: {message}", tr(Some(ctx), "error"));
                return 2;
            }
        },
        None => None,
    };
    if verbose {
        if let Some(profile) = &profile {
            let name = profile["name"].as_str().unwrap_or_default();
            eprintln!(
                "{}",
                trf(Some(ctx), "Using profile: {name}", &[("{name}", name)])
            );
        }
    }

    let mut request = json!({
        "paths": valid_paths,
        "recursive": recursive,
    });
    if let Some(profile) = &profile {
        request["profile_id"] = profile["id"].clone();
        request["profile_name"] = profile["name"].clone();
        request["exclusions"] = profile["exclusions"].clone();
    }
    if verbose {
        for path in request["paths"].as_array().into_iter().flatten() {
            let path = path.as_str().unwrap_or_default();
            eprintln!(
                "{}",
                trf(Some(ctx), "Scanning: {path}", &[("{path}", path)])
            );
        }
    }

    let output_targets = request["paths"].clone();
    let started = Instant::now();
    let result = match dispatch(ctx, "scanner.scan", request) {
        Ok(result) => result,
        Err(error) => {
            eprintln!("{}: {error}", tr(Some(ctx), "error"));
            return 2;
        }
    };
    let duration = started.elapsed().as_secs_f64();
    let threats = collect_threats(&result);
    let infected_count = result["infected_count"]
        .as_u64()
        .unwrap_or(threats.len() as u64);
    let has_errors = scan_has_errors(&result);
    let cancelled = scan_is_cancelled(&result);

    let quarantine_info = if quarantine && !threats.is_empty() {
        Some(quarantine_threats(ctx, &threats))
    } else {
        None
    };

    if json_output {
        let mut output = json!({
            "status": if cancelled { "cancelled" } else if infected_count > 0 { "infected" } else if has_errors { "error" } else { "clean" },
            "scanned_files": result["scanned_files"].as_u64().unwrap_or(0),
            "infected_count": infected_count,
            "duration_seconds": round_hundredths(duration),
            "targets": result["paths"].clone(),
            "threats": threats.iter().map(|threat| json!({
                "file": threat["file_path"].clone(),
                "threat_name": threat["threat_name"].clone(),
                "category": threat["category"].clone(),
                "severity": threat["severity"].clone(),
            })).collect::<Vec<_>>(),
        });
        if output["targets"].is_null() {
            output["targets"] = output_targets;
        }
        if let Some((quarantined, failures)) = &quarantine_info {
            output["quarantined"] = json!(quarantined);
            if !failures.is_empty() {
                output["quarantine_failures"] = Value::Array(failures.clone());
            }
        }
        let errors = scan_errors(&result);
        if !errors.is_empty() {
            output["errors"] = json!(errors);
        }
        print_json(&output);
    } else {
        print_scan_text(
            ctx,
            &result,
            duration,
            &threats,
            quarantine_info.as_ref(),
            has_errors,
        );
    }

    if cancelled {
        130
    } else if infected_count > 0 {
        1
    } else if has_errors {
        2
    } else {
        0
    }
}

fn print_scan_help(ctx: &Context) -> i32 {
    println!(
        "{}",
        tr(
            Some(ctx),
            // Translators: Keep `clamui`, uppercase metavariables, brackets, and all `--` flags unchanged; they are CLI syntax.
            "Usage: clamui scan PATH [PATH ...] [--no-recursive] [--profile NAME] [--quarantine] [--json] [--verbose]"
        )
    );
    println!(
        "{}",
        tr(
            Some(ctx),
            // Translators: Preserve the numeric exit-code meanings.
            "Scan one or more files or directories with ClamAV.\nExit codes: 0 = clean, 1 = threats found, 2 = error."
        )
    );
    0
}

fn validate_scan_paths(ctx: &Context, paths: &[String]) -> Vec<String> {
    paths
        .iter()
        .filter_map(|path| {
            let expanded = expand_path(path);
            match fs::canonicalize(&expanded) {
                Ok(resolved) => Some(resolved.display().to_string()),
                Err(_) => {
                    eprintln!(
                        "error: {}",
                        trf(Some(ctx), "Path not found: {path}", &[("{path}", path)])
                    );
                    None
                }
            }
        })
        .collect()
}

fn find_profile(ctx: &Context, name: &str) -> Result<Value, String> {
    let profiles = dispatch(ctx, "profiles.list", json!({}))?;
    let profiles = profiles["profiles"]
        .as_array()
        .or_else(|| profiles.as_array())
        .ok_or_else(|| "Invalid profiles response".to_owned())?;
    profiles
        .iter()
        .find(|profile| profile["name"].as_str() == Some(name))
        .cloned()
        .ok_or_else(|| trf(Some(ctx), "Profile not found: {name}", &[("{name}", name)]))
}

fn collect_threats(result: &Value) -> Vec<Value> {
    result["threat_details"]
        .as_array()
        .cloned()
        .or_else(|| {
            result["per_target_results"].as_array().map(|targets| {
                targets
                    .iter()
                    .flat_map(|target| {
                        target["threat_details"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .cloned()
                    })
                    .collect()
            })
        })
        .unwrap_or_default()
}

fn scan_has_errors(result: &Value) -> bool {
    result["status"].as_str() == Some("error")
        || result["per_target_results"]
            .as_array()
            .is_some_and(|targets| {
                targets
                    .iter()
                    .any(|target| target["status"].as_str() == Some("error"))
            })
}

fn scan_is_cancelled(result: &Value) -> bool {
    result["status"].as_str() == Some("cancelled")
        || result["per_target_results"]
            .as_array()
            .is_some_and(|targets| {
                targets
                    .iter()
                    .any(|target| target["status"].as_str() == Some("cancelled"))
            })
}

fn scan_errors(result: &Value) -> Vec<String> {
    result["per_target_results"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|target| target["status"].as_str() == Some("error"))
        .filter_map(|target| target["error_message"].as_str().map(ToOwned::to_owned))
        .collect()
}

fn quarantine_threats(ctx: &Context, threats: &[Value]) -> (u64, Vec<Value>) {
    let mut quarantined = 0;
    let mut failures = Vec::new();
    for threat in threats {
        let path = threat["file_path"].as_str().unwrap_or_default();
        let threat_name = threat["threat_name"].as_str().unwrap_or_default();
        match dispatch(ctx, "quarantine.quarantine", json!({ "path": path, "threat_name": threat_name })) {
            Ok(value) if value["status"].as_str() == Some("success") || value["success"].as_bool() == Some(true) => quarantined += 1,
            Ok(value) => failures.push(json!({
                "file": path,
                "error": value["error_message"].as_str().unwrap_or_else(|| value["status"].as_str().unwrap_or("error")),
            })),
            Err(error) => failures.push(json!({ "file": path, "error": error })),
        }
    }
    (quarantined, failures)
}

fn print_scan_text(
    ctx: &Context,
    result: &Value,
    duration: f64,
    threats: &[Value],
    quarantine_info: Option<&(u64, Vec<Value>)>,
    has_errors: bool,
) {
    let count = result["scanned_files"].as_u64().unwrap_or(0);
    let count_display = count.to_string();
    let duration = format!("{duration:.1}");
    println!(
        "{}",
        trnf(
            Some(ctx),
            "Scanned {count} file in {duration:.1f}s",
            "Scanned {count} files in {duration:.1f}s",
            count,
            &[("{count}", &count_display), ("{duration:.1f}", &duration)]
        )
    );
    if !threats.is_empty() {
        let count = threats.len() as u64;
        let count_display = count.to_string();
        println!(
            "{}",
            trnf(
                Some(ctx),
                "\nThreat found: {count}",
                "\nThreats found: {count}",
                count,
                &[("{count}", &count_display)]
            )
        );
        for threat in threats {
            println!(
                "  {}",
                sanitize_line(threat["file_path"].as_str().unwrap_or_default())
            );
            println!(
                "    {} [{}/{}]",
                sanitize_line(threat["threat_name"].as_str().unwrap_or_default()),
                sanitize_line(threat["category"].as_str().unwrap_or_default()),
                sanitize_line(threat["severity"].as_str().unwrap_or_default())
            );
        }
        if let Some((quarantined, failures)) = quarantine_info {
            if *quarantined > 0 {
                let count = quarantined.to_string();
                println!(
                    "{}",
                    trnf(
                        Some(ctx),
                        "\nQuarantined: {count} file",
                        "\nQuarantined: {count} files",
                        *quarantined,
                        &[("{count}", &count)]
                    )
                );
            }
            if !failures.is_empty() {
                println!("{}", tr(Some(ctx), "\nFailed to quarantine:"));
                for failure in failures {
                    println!(
                        "  {}: {}",
                        sanitize_line(failure["file"].as_str().unwrap_or_default()),
                        sanitize_line(failure["error"].as_str().unwrap_or_default())
                    );
                }
            }
        }
    } else if has_errors {
        println!("{}", tr(Some(ctx), "\nScan completed with errors:"));
        for error in scan_errors(result) {
            println!("  {}", sanitize_line(&error));
        }
    } else {
        println!("{}", tr(Some(ctx), "No threats found."));
    }
}

fn run_quarantine(ctx: &Context, args: &[String]) -> i32 {
    if args.is_empty() || matches!(args.first().map(String::as_str), Some("--help" | "-h")) {
        println!(
            "{}",
            tr(
                Some(ctx),
                // Translators: Keep `clamui`, angle-bracket choices, and `[args]` unchanged; they are CLI syntax.
                "Usage: clamui quarantine <list|restore|delete> [args]"
            )
        );
        return 0;
    }
    if has_help(args) {
        let usage = match args[0].as_str() {
            "list" => tr!(
                // Translators: Keep `clamui`, `list`, and `--json` unchanged; they are CLI syntax.
                "Usage: clamui quarantine list [--json]"
            ),
            "restore" => tr!(
                // Translators: Keep `clamui`, `restore`, and `ID` unchanged; they are CLI syntax.
                "Usage: clamui quarantine restore ID"
            ),
            "delete" => tr!(
                // Translators: Keep `clamui`, `delete`, and `ID` unchanged; they are CLI syntax.
                "Usage: clamui quarantine delete ID"
            ),
            _ => tr!(
                // Translators: Keep `clamui`, angle-bracket choices, and `[args]` unchanged; they are CLI syntax.
                "Usage: clamui quarantine <list|restore|delete> [args]"
            ),
        };
        println!("{}", tr(Some(ctx), usage));
        return 0;
    }
    match args[0].as_str() {
        "list" => {
            if args.iter().skip(1).any(|arg| arg != "--json") {
                return argument_error(ctx, "quarantine list accepts only --json");
            }
            let json_output = args.iter().any(|arg| arg == "--json");
            let response = match dispatch(ctx, "quarantine.list", json!({})) {
                Ok(response) => response,
                Err(error) => return operation_error(ctx, error),
            };
            let entries = response["entries"]
                .as_array()
                .cloned()
                .or_else(|| response.as_array().cloned())
                .unwrap_or_default();
            if json_output {
                print_json(&Value::Array(entries));
                return 0;
            }
            if entries.is_empty() {
                println!("{}", tr(Some(ctx), "No quarantined files."));
                return 0;
            }
            let rows: Vec<Vec<String>> = entries
                .iter()
                .map(|entry| {
                    vec![
                        entry["id"].to_string(),
                        sanitize_line(entry["original_path"].as_str().unwrap_or_default()),
                        sanitize_line(entry["threat_name"].as_str().unwrap_or_default()),
                        format_timestamp(entry["detection_date"].as_str()),
                        format_size(entry["file_size"].as_u64().unwrap_or(0)),
                    ]
                })
                .collect();
            print_table(
                &[
                    tr(Some(ctx), "ID"),
                    tr(Some(ctx), "File"),
                    tr(Some(ctx), "Threat"),
                    tr(Some(ctx), "Date"),
                    tr(Some(ctx), "Size"),
                ],
                &rows,
            );
            let total_size = response["total_size"].as_u64().unwrap_or_else(|| {
                entries
                    .iter()
                    .map(|entry| entry["file_size"].as_u64().unwrap_or(0))
                    .sum()
            });
            let count = entries.len() as u64;
            let count_display = count.to_string();
            let size = format_size(total_size);
            println!(
                "\n{}",
                trnf(
                    Some(ctx),
                    "{count} entry ({size} total)",
                    "{count} entries ({size} total)",
                    count,
                    &[("{count}", &count_display), ("{size}", &size)]
                )
            );
            0
        }
        "restore" | "delete" => {
            let (before, after) = split_terminator(&args[1..]);
            let (entry_id, allow_negative_separator) = match after {
                None => match before {
                    [entry_id] => (entry_id, false),
                    _ => {
                        return argument_error(
                            ctx,
                            &trf(
                                Some(ctx),
                                // Translators: Keep `quarantine`, command-valued `{action}`, and `ID` unchanged.
                                "quarantine {action} requires ID",
                                &[("{action}", &args[0])],
                            ),
                        );
                    }
                },
                Some(after) => match (before, after) {
                    ([], [entry_id]) => (entry_id, true),
                    _ => {
                        return argument_error(
                            ctx,
                            &trf(
                                Some(ctx),
                                // Translators: Keep `quarantine`, command-valued `{action}`, and `ID` unchanged.
                                "quarantine {action} requires ID",
                                &[("{action}", &args[0])],
                            ),
                        );
                    }
                },
            };
            let id = match parse_quarantine_entry_id(entry_id, allow_negative_separator) {
                Ok(Some(id)) => id,
                Ok(None) => return quarantine_entry_not_found(ctx, entry_id),
                Err(()) => return argument_error(ctx, "ID must be an integer"),
            };
            let entries = match dispatch(ctx, "quarantine.list", json!({})) {
                Ok(value) => value,
                Err(error) => return operation_error(ctx, error),
            };
            let entry = entries["entries"]
                .as_array()
                .or_else(|| entries.as_array())
                .and_then(|all| all.iter().find(|entry| entry["id"].as_i64() == Some(id)))
                .cloned();
            let Some(entry) = entry else {
                return quarantine_entry_not_found(ctx, entry_id);
            };
            let action = if args[0] == "restore" {
                "quarantine.restore"
            } else {
                "quarantine.delete"
            };
            match dispatch(ctx, action, json!({"id": id})) {
                Ok(result)
                    if result["status"].as_str() == Some("success")
                        || result["success"].as_bool() == Some(true)
                        || result["deleted"].as_bool() == Some(true) =>
                {
                    let verb = if args[0] == "restore" {
                        tr(Some(ctx), "Restored")
                    } else {
                        tr(Some(ctx), "Deleted")
                    };
                    let path = entry["original_path"].as_str().unwrap_or_default();
                    println!(
                        "{}",
                        trf(
                            Some(ctx),
                            "{verb}: {path}",
                            &[("{verb}", &verb), ("{path}", path)]
                        )
                    );
                    0
                }
                Ok(result) => {
                    let prefix = if args[0] == "restore" {
                        tr(Some(ctx), "Restore failed")
                    } else {
                        tr(Some(ctx), "Delete failed")
                    };
                    let error = result["error_message"]
                        .as_str()
                        .unwrap_or_else(|| result["status"].as_str().unwrap_or("error"));
                    eprintln!(
                        "error: {}",
                        trf(
                            Some(ctx),
                            "{prefix}: {error}",
                            &[("{prefix}", &prefix), ("{error}", error)]
                        )
                    );
                    1
                }
                Err(error) => operation_error(ctx, error),
            }
        }
        _ => argument_error(ctx, "unknown quarantine action"),
    }
}

/// Parses the signed decimal integer syntax accepted for a quarantine ID.
///
/// IDs outside SQLite's signed range and negative IDs are well-formed but
/// cannot refer to a normal quarantine entry, so callers report them as an
/// operational not-found result rather than a CLI syntax error.
fn parse_quarantine_entry_id(
    value: &str,
    allow_negative_separator: bool,
) -> Result<Option<i64>, ()> {
    let (negative, digits) = parse_ascii_integer(value)?;
    if negative {
        if !allow_negative_separator && value.starts_with('-') && digits.contains(&b'_') {
            return Err(());
        }
        return Ok(None);
    }

    let mut id = 0_i64;
    for digit in digits {
        if *digit == b'_' {
            continue;
        }
        let Some(next) = id
            .checked_mul(10)
            .and_then(|current| current.checked_add(i64::from(*digit - b'0')))
        else {
            return Ok(None);
        };
        id = next;
    }
    Ok(Some(id))
}

fn parse_ascii_integer(value: &str) -> Result<(bool, &[u8]), ()> {
    let bytes = value
        .trim_matches(|character: char| character.is_ascii_whitespace())
        .as_bytes();
    let (negative, digits) = match bytes.first() {
        Some(b'-') => (true, &bytes[1..]),
        Some(b'+') => (false, &bytes[1..]),
        Some(_) => (false, bytes),
        None => return Err(()),
    };
    if digits.is_empty() {
        return Err(());
    }
    let mut previous_was_digit = false;
    for (index, digit) in digits.iter().enumerate() {
        match digit {
            b'0'..=b'9' => previous_was_digit = true,
            b'_' if previous_was_digit && digits.get(index + 1).is_some_and(u8::is_ascii_digit) => {
                previous_was_digit = false;
            }
            _ => return Err(()),
        }
    }
    Ok((negative, digits))
}

fn quarantine_entry_not_found(ctx: &Context, entry_id: &str) -> i32 {
    eprintln!(
        "error: {}",
        trf(
            Some(ctx),
            "Quarantine entry not found: {id}",
            &[("{id}", entry_id)]
        )
    );
    1
}

fn run_profile(ctx: &Context, args: &[String]) -> i32 {
    if args.is_empty() || matches!(args.first().map(String::as_str), Some("--help" | "-h")) {
        println!(
            "{}",
            tr(
                Some(ctx),
                // Translators: Keep `clamui`, angle-bracket choices, and `[args]` unchanged; they are CLI syntax.
                "Usage: clamui profile <list|show|export|import> [args]"
            )
        );
        return 0;
    }
    if has_help(args) {
        let usage = match args[0].as_str() {
            "list" => tr!(
                // Translators: Keep `clamui`, `list`, and `--json` unchanged; they are CLI syntax.
                "Usage: clamui profile list [--json]"
            ),
            "show" => tr!(
                // Translators: Keep `clamui`, `show`, `NAME`, and `--json` unchanged; they are CLI syntax.
                "Usage: clamui profile show NAME [--json]"
            ),
            "export" => tr!(
                // Translators: Keep `clamui`, `export`, `NAME`, and `FILE` unchanged; they are CLI syntax.
                "Usage: clamui profile export NAME FILE"
            ),
            "import" => tr!(
                // Translators: Keep `clamui`, `import`, and `FILE` unchanged; they are CLI syntax.
                "Usage: clamui profile import FILE"
            ),
            _ => tr!(
                // Translators: Keep `clamui`, angle-bracket choices, and `[args]` unchanged; they are CLI syntax.
                "Usage: clamui profile <list|show|export|import> [args]"
            ),
        };
        println!("{}", tr(Some(ctx), usage));
        return 0;
    }
    match args[0].as_str() {
        "list" => {
            if args.iter().skip(1).any(|arg| arg != "--json") {
                return argument_error(ctx, "profile list accepts only --json");
            }
            let profiles = match dispatch(ctx, "profiles.list", json!({})) {
                Ok(value) => value,
                Err(error) => return operation_error(ctx, error),
            };
            let profiles = profiles["profiles"]
                .as_array()
                .cloned()
                .or_else(|| profiles.as_array().cloned())
                .unwrap_or_default();
            if args.iter().any(|arg| arg == "--json") {
                print_json(&Value::Array(profiles));
                return 0;
            }
            if profiles.is_empty() {
                println!("{}", tr(Some(ctx), "No scan profiles configured."));
                return 0;
            }
            let rows: Vec<Vec<String>> = profiles
                .iter()
                .map(|profile| {
                    let targets = profile["targets"].as_array().cloned().unwrap_or_default();
                    let mut display = targets
                        .iter()
                        .take(2)
                        .filter_map(Value::as_str)
                        .map(sanitize_line)
                        .collect::<Vec<_>>()
                        .join(", ");
                    if targets.len() > 2 {
                        let remaining = (targets.len() - 2).to_string();
                        display.push_str(&trf(Some(ctx), " (+{n} more)", &[("{n}", &remaining)]));
                    }
                    vec![
                        sanitize_line(profile["name"].as_str().unwrap_or_default()),
                        if display.is_empty() {
                            tr(Some(ctx), "(none)")
                        } else {
                            display
                        },
                        if profile["is_default"].as_bool().unwrap_or(false) {
                            tr(Some(ctx), "yes")
                        } else {
                            tr(Some(ctx), "no")
                        },
                        format_timestamp(profile["updated_at"].as_str()),
                    ]
                })
                .collect();
            print_table(
                &[
                    tr(Some(ctx), "Name"),
                    tr(Some(ctx), "Targets"),
                    tr(Some(ctx), "Default"),
                    tr(Some(ctx), "Updated"),
                ],
                &rows,
            );
            let count = profiles.len() as u64;
            let count_display = count.to_string();
            println!(
                "\n{}",
                trnf(
                    Some(ctx),
                    "{count} profile",
                    "{count} profiles",
                    count,
                    &[("{count}", &count_display)]
                )
            );
            0
        }
        "show" => {
            let (name, json_output) = match parse_named_json(ctx, &args[1..], "profile show") {
                Ok(value) => value,
                Err(code) => return code,
            };
            let profile = match find_profile(ctx, &name) {
                Ok(profile) => profile,
                Err(message) => {
                    eprintln!("{}: {message}", tr(Some(ctx), "error"));
                    return 1;
                }
            };
            if json_output {
                print_json(&profile);
                return 0;
            }
            print_profile(ctx, &profile);
            0
        }
        "export" => {
            let (before, after) = split_terminator(&args[1..]);
            let (name, file) = match after {
                None => match before {
                    [name, file] => (name, file),
                    _ => return argument_error(ctx, "profile export requires NAME and FILE"),
                },
                Some(after) => match (before, after) {
                    ([name], [file]) | ([], [name, file]) => (name, file),
                    _ => return argument_error(ctx, "profile export requires NAME and FILE"),
                },
            };
            let profile = match find_profile(ctx, name) {
                Ok(profile) => profile,
                Err(message) => {
                    eprintln!("{}: {message}", tr(Some(ctx), "error"));
                    return 1;
                }
            };
            match dispatch(ctx, "profiles.export", json!({"id": profile["id"]})) {
                Ok(exported) => {
                    let Some(content) = exported["content"].as_str() else {
                        return operation_error(ctx, "Invalid profile export response".to_owned());
                    };
                    if let Err(error) = atomic_write(Path::new(file), content.as_bytes(), 0o600) {
                        return operation_error(ctx, error);
                    }
                    let name = profile["name"].as_str().unwrap_or_default();
                    println!(
                        "{}",
                        trf(
                            Some(ctx),
                            // Translators: Preserve `{name}` as the profile name and `{path}` as its destination; quotation marks may be localized.
                            "Exported '{name}' to {path}",
                            &[("{name}", name), ("{path}", file)]
                        )
                    );
                    0
                }
                Err(error) => operation_error(ctx, error),
            }
        }
        "import" => {
            let (before, after) = split_terminator(&args[1..]);
            let file = match after {
                None => match before {
                    [file] => file,
                    _ => return argument_error(ctx, "profile import requires FILE"),
                },
                Some(after) => match (before, after) {
                    ([], [file]) => file,
                    _ => return argument_error(ctx, "profile import requires FILE"),
                },
            };
            match dispatch(ctx, "profiles.import", json!({"path": file})) {
                Ok(profile) => {
                    let name = profile["name"].as_str().unwrap_or_default();
                    println!(
                        "{}",
                        trf(Some(ctx), "Imported profile: {name}", &[("{name}", name)])
                    );
                    0
                }
                Err(error) => operation_error(ctx, error),
            }
        }
        _ => argument_error(ctx, "unknown profile action"),
    }
}

fn parse_named_json(ctx: &Context, args: &[String], usage: &str) -> Result<(String, bool), i32> {
    let (before, after) = split_terminator(args);
    match after {
        None => match before {
            [name] => Ok((name.clone(), false)),
            [name, flag] if flag == "--json" => Ok((name.clone(), true)),
            [flag, name] if flag == "--json" => Ok((name.clone(), true)),
            _ => Err(argument_error(
                ctx,
                &trf(
                    Some(ctx),
                    // Translators: Preserve command-valued `{usage}`, `NAME`, and the `--json` CLI flag.
                    "{usage} requires NAME and optional --json",
                    &[("{usage}", usage)],
                ),
            )),
        },
        Some(after) => match (before, after) {
            ([], [name]) => Ok((name.clone(), false)),
            ([flag], [name]) if flag == "--json" => Ok((name.clone(), true)),
            _ => Err(argument_error(
                ctx,
                &trf(
                    Some(ctx),
                    // Translators: Preserve command-valued `{usage}`, `NAME`, and the `--json` CLI flag.
                    "{usage} requires NAME and optional --json",
                    &[("{usage}", usage)],
                ),
            )),
        },
    }
}

fn split_terminator(args: &[String]) -> (&[String], Option<&[String]>) {
    args.iter()
        .position(|arg| arg == "--")
        .map_or((args, None), |index| {
            (&args[..index], Some(&args[index + 1..]))
        })
}

fn print_profile(ctx: &Context, profile: &Value) {
    let name = sanitize_line(profile["name"].as_str().unwrap_or_default());
    println!(
        "{}",
        trf(Some(ctx), "Name:        {name}", &[("{name}", &name)])
    );
    let id = profile["id"].to_string();
    println!("{}", trf(Some(ctx), "ID:          {id}", &[("{id}", &id)]));
    let value = if profile["is_default"].as_bool().unwrap_or(false) {
        tr(Some(ctx), "yes")
    } else {
        tr(Some(ctx), "no")
    };
    println!(
        "{}",
        trf(Some(ctx), "Default:     {value}", &[("{value}", &value)])
    );
    if let Some(description) = profile["description"]
        .as_str()
        .filter(|value| !value.is_empty())
    {
        let description = sanitize_line(description);
        println!(
            "{}",
            trf(
                Some(ctx),
                "Description: {description}",
                &[("{description}", &description)]
            )
        );
    }
    let created = format_timestamp(profile["created_at"].as_str());
    println!(
        "{}",
        trf(
            Some(ctx),
            "Created:     {created}",
            &[("{created}", &created)]
        )
    );
    let updated = format_timestamp(profile["updated_at"].as_str());
    println!(
        "{}",
        trf(
            Some(ctx),
            "Updated:     {updated}",
            &[("{updated}", &updated)]
        )
    );
    println!("\n{}", tr(Some(ctx), "Targets:"));
    if let Some(targets) = profile["targets"]
        .as_array()
        .filter(|targets| !targets.is_empty())
    {
        for target in targets {
            println!("  - {}", sanitize_line(target.as_str().unwrap_or_default()));
        }
    } else {
        println!("{}", tr(Some(ctx), "  (none)"));
    }
    let paths = profile["exclusions"]["paths"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let patterns = profile["exclusions"]["patterns"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    if !paths.is_empty() || !patterns.is_empty() {
        println!("\n{}", tr(Some(ctx), "Exclusions:"));
        for path in paths {
            let path = sanitize_line(path.as_str().unwrap_or_default());
            println!(
                "{}",
                trf(Some(ctx), "  path:    {path}", &[("{path}", &path)])
            );
        }
        for pattern in patterns {
            let pattern = sanitize_line(pattern.as_str().unwrap_or_default());
            println!(
                "{}",
                trf(
                    Some(ctx),
                    "  pattern: {pattern}",
                    &[("{pattern}", &pattern)]
                )
            );
        }
    }
    if let Some(options) = profile["options"]
        .as_object()
        .filter(|options| !options.is_empty())
    {
        println!("\n{}", tr(Some(ctx), "Options:"));
        for (key, value) in options {
            let value = value
                .as_str()
                .map_or_else(|| value.to_string(), ToOwned::to_owned);
            println!("  {}: {}", sanitize_line(key), sanitize_line(&value));
        }
    }
}

fn run_status(ctx: &Context, args: &[String]) -> i32 {
    if has_help(args) {
        println!(
            "{}",
            tr(
                Some(ctx),
                // Translators: Keep `clamui` and `--json` unchanged; they are CLI syntax.
                "Usage: clamui status [--json]",
            )
        );
        return 0;
    }
    if args.iter().any(|arg| arg != "--json") {
        return argument_error(ctx, "status accepts only --json");
    }
    let scanner_status = match dispatch(ctx, "scanner.status", json!({})) {
        Ok(value) => value,
        Err(error) => {
            json!({"available": false, "version": null, "error": error, "backend": "unavailable", "daemon_status": "unknown"})
        }
    };
    let daemon_status = scanner_status["daemon_status"].as_str().unwrap_or_else(|| {
        let daemon = &scanner_status["daemon_status"];
        if daemon["connected"].as_bool() == Some(true) {
            "running"
        } else if daemon["clamdscan_available"].as_bool() == Some(true) {
            "stopped"
        } else if daemon.is_object() {
            "not_installed"
        } else {
            "unknown"
        }
    });
    let clamav = json!({
        "available": scanner_status["available"].as_bool().unwrap_or(false),
        "version": scanner_status["version"].clone(),
        "error": scanner_status["error"].clone(),
        "backend": scanner_status["backend"].as_str().unwrap_or("unavailable"),
        "daemon_status": daemon_status,
    });
    let quarantine_status = dispatch(ctx, "quarantine.statistics", json!({}))
        .unwrap_or_else(|_| json!({"entry_count": 0, "total_size": 0}));
    let quarantine = json!({
        "entries": quarantine_status["entries"]
            .as_u64()
            .or_else(|| quarantine_status["entry_count"].as_u64())
            .unwrap_or(0),
        "total_size": quarantine_status["total_size"].as_u64().unwrap_or(0),
    });

    let logs =
        dispatch(ctx, "logs.count", json!({})).unwrap_or_else(|_| json!({"total_entries": 0}));
    let settings = ctx.settings().unwrap_or_else(|_| json!({}));
    if args.iter().any(|arg| arg == "--json") {
        print_json(
            &json!({"clamav": clamav, "quarantine": quarantine, "logs": {"total_entries": logs["total_entries"].as_u64().unwrap_or(0)}, "settings": {"scan_backend": settings["scan_backend"].as_str().unwrap_or("auto"), "notifications_enabled": settings["notifications_enabled"].as_bool().unwrap_or(true)}}),
        );
        return 0;
    }
    println!("{}", tr(Some(ctx), "ClamAV"));
    if clamav["available"].as_bool().unwrap_or(false) {
        let version = clamav["version"].as_str().unwrap_or_default();
        println!(
            "{}",
            trf(
                Some(ctx),
                "  Version:  {version}",
                &[("{version}", version)]
            )
        );
    } else {
        println!("{}", tr(Some(ctx), "  Status:   not available"));
        let error = clamav["error"].as_str().unwrap_or_default();
        println!(
            "{}",
            trf(Some(ctx), "  Error:    {error}", &[("{error}", error)])
        );
    }
    let backend = clamav["backend"].as_str().unwrap_or_default();
    println!(
        "{}",
        trf(
            Some(ctx),
            "  Backend:  {backend}",
            &[("{backend}", backend)]
        )
    );
    let daemon = clamav["daemon_status"].as_str().unwrap_or_default();
    println!(
        "{}",
        trf(Some(ctx), "  Daemon:   {daemon}", &[("{daemon}", daemon)])
    );
    println!("\n{}", tr(Some(ctx), "Quarantine"));
    let quarantine_entries = quarantine["entries"].as_u64().unwrap_or(0).to_string();
    println!(
        "{}",
        trf(
            Some(ctx),
            "  Entries:  {count}",
            &[("{count}", &quarantine_entries)]
        )
    );
    let size = format_size(quarantine["total_size"].as_u64().unwrap_or(0));
    println!(
        "{}",
        trf(Some(ctx), "  Size:     {size}", &[("{size}", &size)])
    );
    println!("\n{}", tr(Some(ctx), "Scan History"));
    let history_entries = logs["total_entries"]
        .as_u64()
        .or_else(|| logs["total_scans"].as_u64())
        .unwrap_or(0)
        .to_string();
    println!(
        "{}",
        trf(
            Some(ctx),
            "  Entries:  {count}",
            &[("{count}", &history_entries)]
        )
    );
    0
}

fn run_history(ctx: &Context, args: &[String]) -> i32 {
    if has_help(args) {
        println!(
            "{}",
            tr(
                Some(ctx),
                // Translators: Keep `clamui`, all `--` flags, `N`, and type choices unchanged; they are CLI syntax.
                "Usage: clamui history [--limit N] [--type scan|update|virustotal] [--json]"
            )
        );
        return 0;
    }
    let mut limit = 20_usize;
    let mut log_type = None;
    let mut json_output = false;
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--json" => json_output = true,
            "--limit" | "-n" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return argument_error(ctx, "--limit requires N");
                };
                match parse_positive_history_limit(value) {
                    Ok(value) => limit = value,
                    Err(()) => return argument_error(ctx, "--limit must be a positive integer"),
                }
            }
            argument if argument.starts_with("--limit=") => {
                match parse_positive_history_limit(&argument[8..]) {
                    Ok(value) => limit = value,
                    Err(()) => return argument_error(ctx, "--limit must be a positive integer"),
                }
            }
            argument if argument.starts_with("-n") && argument.len() > 2 => {
                match parse_positive_history_limit(&argument[2..]) {
                    Ok(value) => limit = value,
                    Err(()) => return argument_error(ctx, "--limit must be a positive integer"),
                }
            }
            "--type" | "-t" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return argument_error(ctx, "--type requires TYPE");
                };
                if !matches!(value.as_str(), "scan" | "update" | "virustotal") {
                    return argument_error(ctx, "--type must be scan, update, or virustotal");
                }
                log_type = Some(value.clone());
            }
            argument if argument.starts_with("-t") && argument.len() > 2 => {
                let value = &argument[2..];
                if !matches!(value, "scan" | "update" | "virustotal") {
                    return argument_error(ctx, "--type must be scan, update, or virustotal");
                }
                log_type = Some(value.to_owned());
            }
            argument if argument.starts_with("--type=") => {
                let value = &argument[7..];
                if !matches!(value, "scan" | "update" | "virustotal") {
                    return argument_error(ctx, "--type must be scan, update, or virustotal");
                }
                log_type = Some(value.to_owned());
            }
            argument => {
                return argument_error(
                    ctx,
                    &trf(
                        Some(ctx),
                        "unrecognized argument: {argument}",
                        &[("{argument}", argument)],
                    ),
                )
            }
        }
        index += 1;
    }
    let mut request = json!({"limit": limit});
    if let Some(log_type) = log_type {
        request["log_type"] = json!(log_type);
    }
    let entries = match dispatch(ctx, "logs.list", request) {
        Ok(entries) => entries,
        Err(error) => {
            eprintln!(
                "error: {}",
                trf(
                    Some(ctx),
                    "Failed to load history: {error}",
                    &[("{error}", error.as_str())]
                )
            );
            return 1;
        }
    };
    let entries = entries.as_array().cloned().unwrap_or_default();
    if json_output {
        print_json(&Value::Array(entries));
        return 0;
    }
    if entries.is_empty() {
        println!("{}", tr(Some(ctx), "No scan history found."));
        return 0;
    }
    let rows: Vec<Vec<String>> = entries
        .iter()
        .map(|entry| {
            let summary = entry["summary"].as_str().unwrap_or_default();
            let summary = if summary.chars().count() > 60 {
                format!("{}…", summary.chars().take(57).collect::<String>())
            } else {
                summary.to_owned()
            };
            vec![
                format_timestamp(entry["timestamp"].as_str()),
                entry["type"].as_str().unwrap_or_default().to_owned(),
                entry["status"].as_str().unwrap_or_default().to_owned(),
                sanitize_line(&summary),
            ]
        })
        .collect();
    print_table(
        &[
            tr(Some(ctx), "Date"),
            tr(Some(ctx), "Type"),
            tr(Some(ctx), "Status"),
            tr(Some(ctx), "Summary"),
        ],
        &rows,
    );
    let total = dispatch(ctx, "logs.count", json!({}))
        .ok()
        .and_then(|value| value["total_entries"].as_u64())
        .unwrap_or(entries.len() as u64);
    if total > entries.len() as u64 {
        let shown = entries.len().to_string();
        let total_count = total;
        let total = total_count.to_string();
        println!(
            "\n{}",
            trnf(
                Some(ctx),
                // Translators: Preserve `{shown}` and `{total}` as counts and keep the `--limit` CLI flag unchanged.
                "Showing {shown} of {total} entry. Use --limit to see more.",
                // Translators: Preserve `{shown}` and `{total}` as counts and keep the `--limit` CLI flag unchanged.
                "Showing {shown} of {total} entries. Use --limit to see more.",
                total_count,
                &[("{shown}", &shown), ("{total}", &total)]
            )
        );
    }
    0
}

fn parse_positive_history_limit(value: &str) -> Result<usize, ()> {
    let (negative, digits) = parse_ascii_integer(value)?;
    if negative {
        return Err(());
    }
    let limit = digits.iter().fold(0_usize, |limit, digit| {
        if *digit == b'_' {
            limit
        } else {
            limit
                .saturating_mul(10)
                .saturating_add(usize::from(*digit - b'0'))
        }
    });
    (limit > 0).then_some(limit).ok_or(())
}

fn run_install_privileged_helper(ctx: &Context, args: &[String]) -> i32 {
    if has_help(args) {
        println!(
            "{}",
            tr(
                Some(ctx),
                // Translators: Keep `clamui install-privileged-helper` unchanged; it is the CLI command.
                "Usage: clamui install-privileged-helper",
            )
        );
        return 0;
    }
    let prefix = match args {
        [] => "/",
        [flag, prefix] if flag == "--prefix" && (prefix == "-" || !prefix.starts_with('-')) => {
            prefix
        }
        [flag] if flag.starts_with("--prefix=") => &flag["--prefix=".len()..],
        _ => return argument_error(ctx, "install-privileged-helper accepts only --prefix PATH"),
    };
    match crate::privileged::install_cli_helper(ctx, Path::new(prefix)) {
        Ok(detail) => {
            println!("{detail}");
            0
        }
        Err(error) => operation_error(ctx, error),
    }
}

fn has_help(args: &[String]) -> bool {
    args.iter()
        .take_while(|arg| arg.as_str() != "--")
        .any(|arg| arg == "--help" || arg == "-h")
}

fn argument_error(ctx: &Context, message: &str) -> i32 {
    eprintln!("{}: {}", tr(Some(ctx), "error"), tr(Some(ctx), message));
    2
}

fn operation_error(ctx: &Context, error: String) -> i32 {
    eprintln!("{}: {error}", tr(Some(ctx), "error"));
    1
}

fn print_json(value: &Value) {
    println!(
        "{}",
        serde_json::to_string_pretty(value).expect("JSON values serialize")
    );
}

fn format_size(bytes: u64) -> String {
    if bytes < 1024 {
        format!("{bytes} B")
    } else if bytes < 1024 * 1024 {
        format!("{:.1} KB", bytes as f64 / 1024.0)
    } else if bytes < 1024 * 1024 * 1024 {
        format!("{:.1} MB", bytes as f64 / (1024.0 * 1024.0))
    } else {
        format!("{:.1} GB", bytes as f64 / (1024.0 * 1024.0 * 1024.0))
    }
}

fn format_timestamp(timestamp: Option<&str>) -> String {
    let Some(timestamp) = timestamp else {
        return "N/A".to_owned();
    };
    chrono::DateTime::parse_from_rfc3339(timestamp)
        .map(|parsed| parsed.format("%Y-%m-%d %H:%M").to_string())
        .or_else(|_| {
            chrono::NaiveDateTime::parse_from_str(timestamp, "%Y-%m-%dT%H:%M:%S%.f")
                .map(|parsed| parsed.format("%Y-%m-%d %H:%M").to_string())
        })
        .unwrap_or_else(|_| timestamp.to_owned())
}

fn print_table(headers: &[String], rows: &[Vec<String>]) {
    if rows.is_empty() {
        return;
    }
    let mut widths = headers.iter().map(String::len).collect::<Vec<_>>();
    for row in rows {
        for (index, cell) in row.iter().enumerate() {
            if index < widths.len() {
                widths[index] = widths[index].max(cell.len());
            }
        }
    }
    let header = headers
        .iter()
        .zip(&widths)
        .map(|(header, width)| format!("{header:<width$}"))
        .collect::<Vec<_>>()
        .join("  ");
    println!("{header}");
    println!("{}", "─".repeat(header.len()));
    for row in rows {
        println!(
            "{}",
            row.iter()
                .enumerate()
                .map(|(index, cell)| if index < widths.len() {
                    format!("{cell:<width$}", width = widths[index])
                } else {
                    cell.clone()
                })
                .collect::<Vec<_>>()
                .join("  ")
        );
    }
}

fn round_hundredths(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}
