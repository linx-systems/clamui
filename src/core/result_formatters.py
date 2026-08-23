# ClamUI Result Formatters
"""
Scan result formatting utilities.

This module provides functions for:
- Formatting ScanResult objects as human-readable text reports
- Formatting ScanResult objects as CSV for spreadsheet export
- Generating exportable scan reports with timestamps and threat details
- Composing aggregated warning and status messages for scan results
"""

import csv
import io
from datetime import datetime
from typing import TYPE_CHECKING

from .i18n import _

if TYPE_CHECKING:
    from .scanner import ScanResult


def compose_scan_warning(skipped_count: int, warning_messages: list[str]) -> str | None:
    """
    Compose the aggregated warning message for a (multi-target) scan.

    Args:
        skipped_count: Number of files that could not be accessed
        warning_messages: Distinct per-target warning messages

    Returns:
        The skipped-file count phrase when files were skipped, otherwise the
        joined distinct per-target messages (e.g. non-fatal scanner warnings),
        or None when there is nothing to warn about.
    """
    if skipped_count > 0:
        return _("{count} file(s) could not be accessed").format(count=skipped_count)
    if warning_messages:
        return "; ".join(warning_messages)
    return None


def clean_scan_status_message(result: "ScanResult") -> str:
    """
    Build the status banner message for a clean scan result.

    Args:
        result: A clean ScanResult

    Returns:
        The banner message, including the skipped-file count or the warning
        message when present. Never renders a bare "0 file(s)" phrase.
    """
    if result.skipped_count > 0:
        return _("Scan complete - No threats found ({count} file(s) not accessible)").format(
            count=result.skipped_count
        )
    if result.warning_message:
        return _("Scan complete - No threats found ({warning})").format(
            warning=result.warning_message
        )
    return _("Scan complete - No threats found")


def format_results_as_text(result: "ScanResult", timestamp: str | None = None) -> str:
    """
    Format scan results as human-readable text for export or clipboard.

    Creates a formatted text report including:
    - Header with scan timestamp and path
    - Summary statistics (files scanned, threats found)
    - Detailed threat list with file path, threat name, category, and severity
    - Status indicator

    Args:
        result: The ScanResult object to format
        timestamp: Optional timestamp string. If not provided, uses current time.

    Returns:
        Formatted text string suitable for export to file or clipboard

    Example output:
        ═══════════════════════════════════════════════════════════════
        ClamUI Scan Report
        ═══════════════════════════════════════════════════════════════
        Scan Date: 2024-01-15 14:30:45
        Scanned Path: /home/user/Downloads
        Status: INFECTED

        ───────────────────────────────────────────────────────────────
        Summary
        ───────────────────────────────────────────────────────────────
        Files Scanned: 150
        Directories Scanned: 25
        Threats Found: 2

        ───────────────────────────────────────────────────────────────
        Detected Threats
        ───────────────────────────────────────────────────────────────

        [1] CRITICAL - Ransomware
            File: /home/user/Downloads/malware.exe
            Threat: Win.Ransomware.Locky

        [2] HIGH - Trojan
            File: /home/user/Downloads/suspicious.doc
            Threat: Win.Trojan.Agent

        ═══════════════════════════════════════════════════════════════
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []

    # Header
    header_line = "═" * 65
    sub_header_line = "─" * 65

    lines.append(header_line)
    lines.append(_("ClamUI Scan Report"))
    lines.append(header_line)
    lines.append(_("Scan Date: {timestamp}").format(timestamp=timestamp))
    lines.append(_("Scanned Path: {path}").format(path=result.path))
    lines.append(_("Status: {status}").format(status=result.status.value.upper()))
    lines.append("")

    # Summary section
    lines.append(sub_header_line)
    lines.append(_("Summary"))
    lines.append(sub_header_line)
    lines.append(_("Files Scanned: {count}").format(count=result.scanned_files))
    lines.append(_("Directories Scanned: {count}").format(count=result.scanned_dirs))
    lines.append(_("Threats Found: {count}").format(count=result.infected_count))
    lines.append("")

    # Threat details section
    if result.threat_details:
        lines.append(sub_header_line)
        lines.append(_("Detected Threats"))
        lines.append(sub_header_line)
        lines.append("")

        for i, threat in enumerate(result.threat_details, 1):
            severity_upper = threat.severity.upper()
            lines.append(
                _("[{index}] {severity} - {category}").format(
                    index=i, severity=severity_upper, category=threat.category
                )
            )
            lines.append(_("    File: {path}").format(path=threat.file_path))
            lines.append(_("    Threat: {name}").format(name=threat.threat_name))
            lines.append("")
    elif result.status.value == "clean":
        lines.append(sub_header_line)
        lines.append(_("No Threats Detected"))
        lines.append(sub_header_line)
        lines.append("")
        lines.append(_("All scanned files are clean."))
        lines.append("")
    elif result.status.value == "error":
        lines.append(sub_header_line)
        lines.append(_("Scan Error"))
        lines.append(sub_header_line)
        lines.append("")
        if result.error_message:
            lines.append(_("Error: {message}").format(message=result.error_message))
        lines.append("")
    elif result.status.value == "cancelled":
        lines.append(sub_header_line)
        lines.append(_("Scan Cancelled"))
        lines.append(sub_header_line)
        lines.append("")
        lines.append(_("The scan was cancelled before completion."))
        lines.append("")

    # Footer
    lines.append(header_line)

    return "\n".join(lines)


def format_results_as_csv(result: "ScanResult", timestamp: str | None = None) -> str:
    """
    Format scan results as CSV for export to spreadsheet applications.

    Creates a CSV formatted string with the following columns:
    - File Path: The path to the infected file
    - Threat Name: The name of the detected threat from ClamAV
    - Category: The threat category (Ransomware, Trojan, etc.)
    - Severity: The severity level (critical, high, medium, low)
    - Timestamp: When the scan was performed

    Uses Python's csv module for proper escaping of special characters
    (commas, quotes, newlines) in file paths and threat names.

    Args:
        result: The ScanResult object to format
        timestamp: Optional timestamp string. If not provided, uses current time.

    Returns:
        CSV formatted string suitable for export to .csv file

    Example output:
        File Path,Threat Name,Category,Severity,Timestamp
        /home/user/malware.exe,Win.Ransomware.Locky,Ransomware,critical,2024-01-15 14:30:45
        /home/user/suspicious.doc,Win.Trojan.Agent,Trojan,high,2024-01-15 14:30:45
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Use StringIO to write CSV to a string
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Write header row
    writer.writerow(
        [_("File Path"), _("Threat Name"), _("Category"), _("Severity"), _("Timestamp")]
    )

    # Write threat details
    if result.threat_details:
        for threat in result.threat_details:
            writer.writerow(
                [threat.file_path, threat.threat_name, threat.category, threat.severity, timestamp]
            )

    return output.getvalue()
