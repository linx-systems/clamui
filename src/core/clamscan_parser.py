# ClamUI Clamscan Result Parser
"""Stateless parsing of clamscan process output."""

import re

from .scanner_base import collect_clamav_warnings, resolve_exit2_status
from .scanner_types import ScanResult, ScanStatus, ThreatDetail
from .threat_classifier import categorize_threat, classify_threat_severity_str


def parse_clamscan_result(
    path: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    scanned_files_hint: int = 0,
) -> ScanResult:
    """
    Parse clamscan output into a ScanResult.

    ClamAV exit codes:
    - 0: No virus found
    - 1: Virus(es) found
    - 2: Some error(s) occurred

    Args:
        path: The scanned path
        stdout: Standard output from clamscan
        stderr: Standard error from clamscan
        exit_code: Process exit code
        scanned_files_hint: Files observed by live progress parsing. Used
            only when the terminal scan summary is absent from captured
            output.

    Returns:
        Parsed ScanResult
    """
    infected_files = []
    threat_details = []
    skipped_files, nonfatal_warnings, hard_error_lines = collect_clamav_warnings(stdout, stderr)
    scanned_files: int | None = None
    scanned_dirs = 0
    infected_count = 0

    # Parse stdout line by line
    for line in stdout.splitlines():
        line = line.strip()

        # Regex pattern: "/path/to/file: ThreatName FOUND"
        # Uses rsplit to handle colons in file paths (e.g., Windows C:\)
        # Look for infected file lines (format: "/path/to/file: Virus.Name FOUND")
        # Skip verbose "Scanning <path>" lines so a clean file whose name
        # ends in "FOUND" is not misparsed as a detection (mirrors on_line).
        if line.startswith("Scanning "):
            continue

        if line.endswith("FOUND"):
            # Extract file path and threat name
            # Format: "/path/to/file: ThreatName FOUND"
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                file_path = parts[0].strip()
                # Extract threat name (remove " FOUND" suffix)
                threat_part = parts[1].strip()
                threat_name = (
                    threat_part.rsplit(" ", 1)[0].strip()
                    if " FOUND" in threat_part
                    else threat_part
                )

                infected_files.append(file_path)

                # Create ThreatDetail with classification
                threat_detail = ThreatDetail(
                    file_path=file_path,
                    threat_name=threat_name,
                    category=categorize_threat(threat_name),
                    severity=classify_threat_severity_str(threat_name),
                )
                threat_details.append(threat_detail)
                infected_count += 1

        # Regex pattern for statistics: "Scanned files: 123"
        # Captures numeric value after the label
        # Look for individual summary lines from ClamAV output
        # Format: "Scanned files: 10" or "Scanned directories: 1" or "Infected files: 0"
        elif line.startswith("Scanned files:"):
            match = re.search(r"Scanned files:\s*(\d+)", line)
            if match:
                scanned_files = int(match.group(1))
        elif line.startswith("Scanned directories:"):
            match = re.search(r"Scanned directories:\s*(\d+)", line)
            if match:
                scanned_dirs = int(match.group(1))

    # Verbose output is intentionally capped to bound memory use. If that
    # drops the terminal summary, the streaming callback's completed-file
    # count still proves that the scan processed files. An explicit
    # "Scanned files: 0" summary remains authoritative.
    if scanned_files is None:
        scanned_files = scanned_files_hint

    # Determine overall status based on exit code
    warning_message = None
    exit2_error_message = None
    if infected_count > 0:
        # Detections are authoritative: clamscan returns exit code 2 when it
        # both finds a virus and hits an error (e.g. an unreadable file), so
        # never let an error code mask a real threat.
        status = ScanStatus.INFECTED
        if exit_code == 2 and skipped_files:
            warning_message = f"{len(skipped_files)} file(s) could not be accessed"
    elif exit_code == 0:
        status = ScanStatus.CLEAN
    elif exit_code == 1:
        status = ScanStatus.INFECTED
    elif exit_code == 2:
        status, warning_message, exit2_error_message = resolve_exit2_status(
            stdout, scanned_files, hard_error_lines, skipped_files, nonfatal_warnings
        )
    else:
        status = ScanStatus.ERROR

    error_message = None
    if status == ScanStatus.ERROR:
        error_message = (
            exit2_error_message
            or stderr.strip()
            or (hard_error_lines[0] if hard_error_lines else None)
        )

    return ScanResult(
        status=status,
        path=path,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        infected_files=infected_files,
        scanned_files=scanned_files,
        scanned_dirs=scanned_dirs,
        infected_count=infected_count,
        error_message=error_message,
        threat_details=threat_details,
        skipped_files=skipped_files,
        skipped_count=len(skipped_files),
        warning_message=warning_message,
        nonfatal_warnings=nonfatal_warnings,
    )
