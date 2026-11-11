use crate::common::path_to_wire;
use crate::scanner::{ScanResult, ScanStatus, ThreatDetail};
use crate::threat::{categorize, classify_severity};
use std::ffi::OsStr;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;

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
    hard_errors: Vec<(String, bool)>,
}

#[derive(Default)]
pub(crate) struct StreamEvidence {
    warnings: WarningEvidence,
    threats: Vec<ThreatDetail>,
    daemon: bool,
    scanned_files: Option<u64>,
    scanned_dirs: u64,
    total_errors: Option<u64>,
    first_stdout_line: Option<String>,
}

struct ScanEvidence<'a> {
    backend: BackendEvidence,
    path: &'a str,
    stdout: String,
    stderr: String,
    exit_code: i32,
    scanned_files: u64,
    scanned_dirs: u64,
    stream: StreamEvidence,
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
    let mut stream = StreamEvidence::default();
    for line in stdout.lines() {
        stream.observe(line.as_bytes(), true, true);
    }
    for line in stderr.lines() {
        stream.observe(line.as_bytes(), false, true);
    }
    stream.finish(
        BackendEvidence::Clamscan,
        path,
        stdout.into(),
        stderr.into(),
        exit_code,
        (scanned_files_hint, 0),
    )
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
    let mut stream = StreamEvidence::new(true);
    for line in stdout.lines() {
        stream.observe(line.as_bytes(), true, true);
    }
    for line in stderr.lines() {
        stream.observe(line.as_bytes(), false, true);
    }
    stream.finish(
        BackendEvidence::Daemon { precounted: true },
        path,
        stdout.into(),
        stderr.into(),
        exit_code,
        (scanned_files, scanned_dirs),
    )
}

impl StreamEvidence {
    pub(crate) fn new(daemon: bool) -> Self {
        Self {
            daemon,
            ..Self::default()
        }
    }

    pub(crate) fn observe(&mut self, raw: &[u8], stdout: bool, displayed: bool) {
        let decoded = String::from_utf8_lossy(raw);
        let line = trim_ascii(&decoded);
        if line.is_empty() {
            return;
        }
        if stdout {
            if self.first_stdout_line.is_none() && !line.contains("SCAN SUMMARY") {
                self.first_stdout_line = Some(line.to_owned());
            }
            if self.daemon || !line.starts_with("Scanning ") {
                if let Some(threat) = detection(raw) {
                    self.threats.push(threat);
                }
            }
            if let Some(value) = line.strip_prefix("Scanned files:") {
                self.scanned_files = value.trim().parse().ok();
            } else if let Some(value) = line.strip_prefix("Scanned directories:") {
                self.scanned_dirs = value.trim().parse().unwrap_or(0);
            } else if let Some(value) = line.strip_prefix("Total errors:") {
                if self.total_errors.is_none() {
                    self.total_errors = value.trim().parse().ok();
                }
            }
        }
        if let Some(path) = skipped_path(&decoded) {
            let path = wire_path(raw, &decoded, path);
            if !self.warnings.skipped_files.contains(&path) {
                self.warnings.skipped_files.push(path);
            }
            return;
        }
        if line.contains("LibClamAV Warning: cli_realpath: Invalid arguments.") {
            return;
        }
        if line.starts_with("LibClamAV Error:")
            && (line.contains("index_local_file_headers_within_bounds")
                || line.contains("Invalid offset arguments"))
        {
            return;
        }
        if (line.starts_with("LibClamAV Warning:") && {
            let lower = line.to_ascii_lowercase();
            NONFATAL_WARNING_MARKERS
                .iter()
                .any(|marker| lower.contains(marker))
        }) || line.contains(": Time limit reached")
        {
            self.warnings.nonfatal_warnings.push(line.to_owned());
        } else if line.starts_with("WARNING:")
            || line.starts_with("ERROR:")
            || line.starts_with("LibClamAV Error:")
            || line.starts_with("LibClamAV Warning:")
            || line.ends_with("ERROR")
        {
            self.warnings.hard_errors.push((line.to_owned(), displayed));
        }
    }

    pub(crate) fn merge_stderr(&mut self, stderr: Self) {
        for path in stderr.warnings.skipped_files {
            if !self.warnings.skipped_files.contains(&path) {
                self.warnings.skipped_files.push(path);
            }
        }
        self.warnings
            .nonfatal_warnings
            .extend(stderr.warnings.nonfatal_warnings);
        self.warnings
            .hard_errors
            .extend(stderr.warnings.hard_errors);
    }

    pub(crate) fn finish(
        self,
        backend: BackendEvidence,
        path: &str,
        stdout: String,
        stderr: String,
        exit_code: i32,
        (files, dirs): (u64, u64),
    ) -> ScanResult {
        let (scanned_files, scanned_dirs) = match backend {
            BackendEvidence::Clamscan => (self.scanned_files.unwrap_or(files), self.scanned_dirs),
            BackendEvidence::Daemon { .. } => (files, dirs),
        };
        interpret(ScanEvidence {
            backend,
            path,
            stdout,
            stderr,
            exit_code,
            scanned_files,
            scanned_dirs,
            stream: self,
        })
    }
}

pub(crate) fn detection(raw: &[u8]) -> Option<ThreatDetail> {
    let raw = trim_ascii_end(raw);
    if !raw.ends_with(b"FOUND") {
        return None;
    }
    let separator = raw.iter().rposition(|byte| *byte == b':')?;
    let file_path = &raw[..separator];
    let value = String::from_utf8_lossy(&raw[separator + 1..]);
    let threat_name = value
        .trim()
        .strip_suffix(" FOUND")
        .unwrap_or(value.trim())
        .trim();
    if file_path.is_empty() || threat_name.is_empty() {
        return None;
    }
    Some(ThreatDetail {
        file_path: path_to_wire(Path::new(OsStr::from_bytes(file_path))),
        threat_name: threat_name.to_owned(),
        category: categorize(Some(threat_name)),
        severity: classify_severity(Some(threat_name)).as_str().to_owned(),
    })
}

fn trim_ascii(value: &str) -> &str {
    value.trim_matches(|character: char| character.is_ascii_whitespace())
}

fn trim_ascii_end(mut value: &[u8]) -> &[u8] {
    while value.last().is_some_and(u8::is_ascii_whitespace) {
        value = &value[..value.len() - 1];
    }
    value
}

// The parser classifies decoded text, but the corresponding byte range is the
// identity needed for filesystem operations, even for non-UTF-8 filenames.
pub(crate) fn wire_path(raw: &[u8], decoded: &str, path: &str) -> String {
    let start = path.as_ptr() as usize - decoded.as_ptr() as usize;
    let end = start + path.len();
    let raw_start = decoded_offset(raw, start);
    let raw_end = decoded_offset(raw, end);
    path_to_wire(Path::new(OsStr::from_bytes(&raw[raw_start..raw_end])))
}

fn decoded_offset(raw: &[u8], target: usize) -> usize {
    let mut source = 0;
    let mut decoded = 0;
    while source < raw.len() {
        match std::str::from_utf8(&raw[source..]) {
            Ok(_) => return source + target.saturating_sub(decoded),
            Err(error) => {
                let valid = error.valid_up_to();
                if target <= decoded + valid {
                    return source + target - decoded;
                }
                source += valid;
                decoded += valid;
                let invalid = error.error_len().unwrap_or(raw.len() - source);
                source += invalid;
                decoded += '\u{fffd}'.len_utf8();
                if target <= decoded {
                    return source;
                }
            }
        }
    }
    source
}

fn skipped_path(line: &str) -> Option<&str> {
    if let Some(path) = line.strip_prefix("ERROR: Can't access file ") {
        return nonempty_path(path);
    }
    for marker in SKIP_MARKERS {
        if let Some((before, _)) = line.split_once(marker) {
            let path = before
                .strip_prefix("WARNING: ")
                .or_else(|| before.strip_prefix("ERROR: "))
                .unwrap_or(before);
            if path != "WARNING" && path != "ERROR" {
                return nonempty_path(path);
            }
        }
    }
    if let Some(path) = line.strip_prefix("WARNING: Can't open file ") {
        return nonempty_path(
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
            .and_then(|(path, _)| nonempty_path(path));
    }
    None
}

fn nonempty_path(value: &str) -> Option<&str> {
    (!value.is_empty()).then_some(value)
}

fn nonempty(value: &str) -> Option<&str> {
    (!value.trim().is_empty()).then_some(value.trim())
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
        stream,
    } = scan;
    let StreamEvidence {
        warnings: evidence,
        threats: threat_details,
        total_errors,
        first_stdout_line,
        ..
    } = stream;
    let total_errors = total_errors.unwrap_or(0);
    let infected_files = threat_details
        .iter()
        .map(|threat| threat.file_path.clone())
        .collect::<Vec<_>>();
    let hard_genuine = evidence
        .hard_errors
        .iter()
        .any(|(line, _)| genuine_error(line));
    let mut status = ScanStatus::Error;
    let mut warning_message = None;
    let mut error_message = None;
    let mut used_first_hard_error = false;

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
        warning_message = Some("Threats were detected, but details are unavailable.".into());
    } else if exit_code == 2 {
        let positive = !evidence.skipped_files.is_empty()
            || !evidence.nonfatal_warnings.is_empty()
            || total_errors > 0;
        let precounted = matches!(backend, BackendEvidence::Daemon { precounted: true });
        let all_failed = if precounted {
            scanned_files > 0
                && (evidence.skipped_files.len() as u64 >= scanned_files
                    || total_errors >= scanned_files)
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
            } else if total_errors > 0 {
                let count = total_errors;
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
        error_message = nonempty(&stderr).map(str::to_owned);
        if error_message.is_none() {
            if let Some((line, _)) = evidence.hard_errors.first() {
                error_message = Some(line.clone());
                used_first_hard_error = true;
            }
        }
        if error_message.is_none() && matches!(backend, BackendEvidence::Daemon { .. }) {
            error_message = first_stdout_line;
        }
    }

    // Errors outside the retained display transcript still need to reach consumers.
    let omitted_errors = evidence
        .hard_errors
        .iter()
        .enumerate()
        .filter(|(index, (_, displayed))| !*displayed && !(*index == 0 && used_first_hard_error))
        .map(|(_, (line, _))| line.as_str())
        .collect::<Vec<_>>();
    if !omitted_errors.is_empty() {
        let omitted = omitted_errors.join("\n");
        if error_message.is_none() {
            error_message = Some(omitted);
        } else if let Some(message) = &mut error_message {
            message.push('\n');
            message.push_str(&omitted);
        }
    }

    let skipped_count = evidence.skipped_files.len() as u64;
    ScanResult {
        status,
        path: path.to_owned(),
        stdout,
        stderr,
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
