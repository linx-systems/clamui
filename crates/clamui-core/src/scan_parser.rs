use crate::scanner::{ScanResult, ScanStatus, ThreatDetail};
use crate::threat::{categorize, classify_severity};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BackendEvidence {
    Clamscan,
    Daemon { precounted: bool },
}

const SKIP_MARKERS: &[&str] = &[
    ": Failed to open file",
    ": File path check failure:",
    ": Not supported file type",
    ": Can't access file",
    ": Access denied",
];
const NONFATAL_WARNING_MARKERS: &[&str] = &[
    "exceeds limits",
    "file truncated",
    "size limit reached",
    "recursion limit",
    "max recursion level reached",
    "cannot dlopen libclamunrar",
    "bytecode run timed out",
];

#[derive(Default)]
struct WarningEvidence {
    skipped_files: Vec<String>,
    nonfatal_warnings: Vec<String>,
    hard_errors: Vec<String>,
}

struct ScanEvidence<'a> {
    backend: BackendEvidence,
    path: &'a str,
    stdout: &'a str,
    stderr: &'a str,
    exit_code: i32,
    scanned_files: u64,
    scanned_dirs: u64,
    threat_details: Vec<ThreatDetail>,
}

/// Parse a standalone `clamscan` transcript. Summary counts, including an
/// explicit zero, are authoritative; `scanned_files_hint` is used only when a
/// bounded stream omitted the final summary.
pub fn interpret_clamscan(
    path: &str,
    stdout: &str,
    stderr: &str,
    exit_code: i32,
    scanned_files_hint: u64,
) -> ScanResult {
    let (scanned_files, scanned_dirs) = clamscan_counts(stdout, scanned_files_hint);
    let threats = detections(
        stdout
            .lines()
            .filter(|line| !line.trim_start().starts_with("Scanning ")),
    );
    interpret(ScanEvidence {
        backend: BackendEvidence::Clamscan,
        path,
        stdout,
        stderr,
        exit_code,
        scanned_files,
        scanned_dirs,
        threat_details: threats,
    })
}

/// Parse a `clamdscan` transcript. Its counts are pre-count evidence, where a
/// zero count means unknown when traversal was intentionally skipped.
pub fn interpret_daemon(
    path: &str,
    stdout: &str,
    stderr: &str,
    exit_code: i32,
    scanned_files: u64,
    scanned_dirs: u64,
) -> ScanResult {
    interpret(ScanEvidence {
        backend: BackendEvidence::Daemon { precounted: true },
        path,
        stdout,
        stderr,
        exit_code,
        scanned_files,
        scanned_dirs,
        threat_details: detections(stdout.lines()),
    })
}

fn clamscan_counts(stdout: &str, fallback: u64) -> (u64, u64) {
    let mut files = None;
    let mut dirs = 0;
    for line in stdout.lines().map(str::trim) {
        if let Some(value) = line.strip_prefix("Scanned files:") {
            files = value.trim().parse().ok();
        } else if let Some(value) = line.strip_prefix("Scanned directories:") {
            dirs = value.trim().parse().unwrap_or(0);
        }
    }
    (files.unwrap_or(fallback), dirs)
}

fn detections<'a>(lines: impl Iterator<Item = &'a str>) -> Vec<ThreatDetail> {
    lines
        .filter_map(|raw| {
            let line = raw.trim();
            if !line.ends_with("FOUND") {
                return None;
            }
            let (file_path, value) = line.rsplit_once(':')?;
            let threat_name = value
                .trim()
                .strip_suffix(" FOUND")
                .unwrap_or(value.trim())
                .trim();
            if file_path.trim().is_empty() || threat_name.is_empty() {
                return None;
            }
            Some(ThreatDetail {
                file_path: file_path.trim().to_owned(),
                threat_name: threat_name.to_owned(),
                category: categorize(Some(threat_name)),
                severity: classify_severity(Some(threat_name)).as_str().to_owned(),
            })
        })
        .collect()
}

fn warning_evidence(stdout: &str, stderr: &str) -> WarningEvidence {
    let mut evidence = WarningEvidence::default();
    for line in stdout
        .lines()
        .chain(stderr.lines())
        .map(str::trim)
        .filter(|line| !line.is_empty())
    {
        if let Some(path) = skipped_path(line) {
            if !evidence.skipped_files.iter().any(|known| known == path) {
                evidence.skipped_files.push(path.to_owned());
            }
            continue;
        }
        if line.contains("LibClamAV Warning: cli_realpath: Invalid arguments.") {
            continue;
        }
        let lower = line.to_ascii_lowercase();
        if line.starts_with("LibClamAV Error:")
            && (line.contains("index_local_file_headers_within_bounds")
                || line.contains("Invalid offset arguments"))
        {
            continue;
        }
        if (line.starts_with("LibClamAV Warning:")
            && NONFATAL_WARNING_MARKERS
                .iter()
                .any(|marker| lower.contains(marker)))
            || line.contains(": Time limit reached")
        {
            evidence.nonfatal_warnings.push(line.to_owned());
            continue;
        }
        if line.starts_with("WARNING:")
            || line.starts_with("ERROR:")
            || line.starts_with("LibClamAV Error:")
            || line.starts_with("LibClamAV Warning:")
            || line.ends_with("ERROR")
        {
            evidence.hard_errors.push(line.to_owned());
        }
    }
    evidence
}

fn skipped_path(line: &str) -> Option<&str> {
    if let Some(path) = line.strip_prefix("ERROR: Can't access file ") {
        return nonempty(path);
    }
    for marker in SKIP_MARKERS {
        if let Some((before, _)) = line.split_once(marker) {
            let path = before
                .trim()
                .trim_start_matches("WARNING:")
                .trim_start_matches("ERROR:")
                .trim();
            if path != "WARNING" && path != "ERROR" {
                return nonempty(path);
            }
        }
    }
    if let Some(path) = line.strip_prefix("WARNING: Can't open file ") {
        return nonempty(
            path.rsplit_once(':')
                .map_or(path, |(candidate, _)| candidate),
        );
    }
    if line.contains(": Access denied")
        && !line.starts_with("WARNING:")
        && !line.starts_with("ERROR:")
    {
        return line
            .split_once(": Access denied")
            .and_then(|(path, _)| nonempty(path));
    }
    None
}

fn nonempty(value: &str) -> Option<&str> {
    (!value.trim().is_empty()).then_some(value.trim())
}

fn total_errors(stdout: &str) -> u64 {
    stdout
        .lines()
        .map(str::trim)
        .find_map(|line| {
            line.strip_prefix("Total errors:")
                .and_then(|value| value.trim().parse().ok())
        })
        .unwrap_or(0)
}

fn genuine_error(line: &str) -> bool {
    line.ends_with(" ERROR") || line.starts_with("ERROR:") || line.starts_with("LibClamAV Error:")
}

fn interpret(scan: ScanEvidence<'_>) -> ScanResult {
    let ScanEvidence {
        backend,
        path,
        stdout,
        stderr,
        exit_code,
        scanned_files,
        scanned_dirs,
        threat_details,
    } = scan;
    let evidence = warning_evidence(stdout, stderr);
    let infected_files = threat_details
        .iter()
        .map(|threat| threat.file_path.clone())
        .collect::<Vec<_>>();
    let hard_genuine = evidence.hard_errors.iter().any(|line| genuine_error(line));
    let mut status = ScanStatus::Error;
    let mut warning_message = None;
    let mut error_message = None;

    if !threat_details.is_empty() {
        status = ScanStatus::Infected;
        if exit_code == 2 && !evidence.skipped_files.is_empty() {
            let count = evidence.skipped_files.len();
            warning_message = Some(format!(
                "{count} {} could not be accessed",
                if count == 1 { "file" } else { "files" }
            ));
        }
    } else if exit_code == 0 {
        status = if matches!(backend, BackendEvidence::Daemon { .. }) && hard_genuine {
            ScanStatus::Error
        } else {
            ScanStatus::Clean
        };
    } else if exit_code == 1 {
        status = ScanStatus::Infected;
    } else if exit_code == 2 {
        let positive = !evidence.skipped_files.is_empty()
            || !evidence.nonfatal_warnings.is_empty()
            || total_errors(stdout) > 0;
        let precounted = matches!(backend, BackendEvidence::Daemon { precounted: true });
        let all_failed = if precounted {
            scanned_files > 0
                && (evidence.skipped_files.len() as u64 >= scanned_files
                    || total_errors(stdout) >= scanned_files)
        } else {
            scanned_files == 0
        };
        if positive && evidence.hard_errors.is_empty() && !all_failed {
            status = ScanStatus::Clean;
            warning_message = if !evidence.skipped_files.is_empty() {
                let count = evidence.skipped_files.len();
                Some(format!(
                    "{count} {} could not be accessed",
                    if count == 1 { "file" } else { "files" }
                ))
            } else if total_errors(stdout) > 0 {
                let count = total_errors(stdout);
                Some(format!(
                    "{count} {} could not be read",
                    if count == 1 { "file" } else { "files" }
                ))
            } else {
                let count = evidence.nonfatal_warnings.len();
                Some(format!(
                    "{count} non-fatal {} during scan; some files may have been only partially scanned",
                    if count == 1 { "warning" } else { "warnings" }
                ))
            };
        } else if all_failed {
            status = ScanStatus::Error;
            error_message = Some("No files could be scanned".into());
        }
    }

    if status == ScanStatus::Error && error_message.is_none() {
        error_message = nonempty(stderr)
            .map(str::to_owned)
            .or_else(|| evidence.hard_errors.first().cloned());
        if error_message.is_none() && matches!(backend, BackendEvidence::Daemon { .. }) {
            error_message = stdout
                .lines()
                .map(str::trim)
                .find(|line| !line.is_empty() && !line.contains("SCAN SUMMARY"))
                .map(str::to_owned);
        }
    }

    let skipped_count = evidence.skipped_files.len() as u64;
    ScanResult {
        status,
        path: path.to_owned(),
        stdout: stdout.to_owned(),
        stderr: stderr.to_owned(),
        exit_code,
        infected_files,
        scanned_files,
        scanned_dirs,
        infected_count: threat_details.len() as u64,
        error_message,
        threat_details,
        skipped_files: evidence.skipped_files,
        skipped_count,
        warning_message,
        nonfatal_warnings: evidence.nonfatal_warnings,
        backend: match backend {
            BackendEvidence::Clamscan => "clamscan",
            BackendEvidence::Daemon { .. } => "daemon",
        }
        .into(),
    }
}
