# ClamUI VirusTotal Integration Module
"""
VirusTotal API v3 client for file scanning.

This module provides the VirusTotalClient class for scanning files using
the VirusTotal API. It supports:
- SHA256 hash lookup for known files
- File upload for unknown files
- Rate limiting (4 requests/minute for free tier)
- Exponential backoff for retries
- Async scanning using threading + GLib.idle_add pattern
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import certifi
import requests

from .i18n import _

logger = logging.getLogger(__name__)

# VirusTotal API configuration
VT_API_BASE = "https://www.virustotal.com/api/v3"
VT_MAX_FILE_SIZE = 650 * 1024 * 1024  # 650MB limit
VT_DIRECT_UPLOAD_MAX = 32 * 1024 * 1024  # POST /files only accepts files up to 32MB
VT_RATE_LIMIT_REQUESTS = 4
VT_RATE_LIMIT_WINDOW = 60  # seconds
VT_REQUEST_TIMEOUT = 30  # seconds
VT_UPLOAD_TIMEOUT = 300  # 5 minutes for large file uploads
VT_MAX_RETRIES = 3
VT_RETRY_BASE_DELAY = 2  # seconds


class VTScanStatus(Enum):
    """Status of a VirusTotal scan operation."""

    CLEAN = "clean"
    DETECTED = "detected"
    ERROR = "error"
    PENDING = "pending"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    FILE_TOO_LARGE = "file_too_large"


@dataclass
class VTDetection:
    """Detection details from a single antivirus engine."""

    engine_name: str
    category: str  # "malicious", "suspicious", "undetected", "harmless", etc.
    result: str | None  # Threat name if detected, None if clean


@dataclass
class VTScanResult:
    """Result of a VirusTotal scan operation."""

    status: VTScanStatus
    file_path: str
    sha256: str = ""
    detections: int = 0
    total_engines: int = 0
    detection_details: list[VTDetection] = field(default_factory=list)
    scan_date: str | None = None
    permalink: str | None = None
    error_message: str | None = None
    duration: float = 0.0

    @property
    def is_clean(self) -> bool:
        """Check if file is clean (no malicious detections)."""
        return self.status in (VTScanStatus.CLEAN, VTScanStatus.NOT_FOUND)

    @property
    def has_threats(self) -> bool:
        """Check if file has threats detected."""
        return self.status == VTScanStatus.DETECTED

    @property
    def is_error(self) -> bool:
        """Check if scan resulted in an error."""
        return self.status in (
            VTScanStatus.ERROR,
            VTScanStatus.RATE_LIMITED,
            VTScanStatus.FILE_TOO_LARGE,
        )


class VirusTotalClient:
    """
    Client for VirusTotal API v3.

    Handles file scanning with:
    - SHA256 hash checking before upload (faster for known files)
    - File upload for unknown files
    - Rate limiting (4 req/min for free tier)
    - Exponential backoff retries for network failures
    - File size validation (650MB limit)

    Usage:
        client = VirusTotalClient(api_key="your_api_key")

        # Synchronous scan
        result = client.scan_file_sync("/path/to/file")

        # Asynchronous scan with callback
        client.scan_file_async("/path/to/file", callback=on_scan_complete)
    """

    def __init__(self, api_key: str | None = None):
        """
        Initialize the VirusTotal client.

        Args:
            api_key: VirusTotal API key. If None, must be set before scanning.
        """
        self._api_key = api_key
        self._request_times: list[float] = []
        self._lock = threading.Lock()
        self._session: requests.Session | None = None
        self._cancelled = False

    def _get_session(self) -> requests.Session:
        """Get or create a requests session with API key header."""
        if self._session is None:
            self._session = requests.Session()
            # Pin TLS verification to the bundled CA store and refuse to honour
            # REQUESTS_CA_BUNDLE / HTTP(S)_PROXY env vars so a local attacker
            # cannot silently MITM the VirusTotal connection.
            self._session.verify = certifi.where()
            self._session.trust_env = False
            if self._api_key:
                self._session.headers["x-apikey"] = self._api_key
        return self._session

    def set_api_key(self, api_key: str) -> None:
        """
        Set or update the API key.

        Args:
            api_key: The VirusTotal API key.
        """
        self._api_key = api_key
        # Reset session to update headers
        if self._session:
            self._session.close()
            self._session = None

    def cancel(self) -> None:
        """Cancel any ongoing scan operation."""
        self._cancelled = True

    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits using a sliding window algorithm.

        Maintains a list of request timestamps and removes those older than
        VT_RATE_LIMIT_WINDOW (60 seconds). If fewer than VT_RATE_LIMIT_REQUESTS
        (4) remain in the window, allows the request and appends the current
        timestamp.

        Returns:
            True if OK to proceed, False if rate limited.
        """
        with self._lock:
            now = time.time()
            # Remove requests older than the rate limit window
            self._request_times = [t for t in self._request_times if now - t < VT_RATE_LIMIT_WINDOW]

            if len(self._request_times) >= VT_RATE_LIMIT_REQUESTS:
                return False

            self._request_times.append(now)
            return True

    def _wait_for_rate_limit(self) -> bool:
        """
        Wait until rate limit allows a new request.

        Returns:
            True if we can proceed, False if cancelled while waiting.
        """
        while not self._check_rate_limit():
            if self._cancelled:
                return False
            # Calculate wait time until oldest request expires
            with self._lock:
                if self._request_times:
                    oldest = min(self._request_times)
                    wait_time = max(0.1, VT_RATE_LIMIT_WINDOW - (time.time() - oldest) + 0.1)
                else:
                    wait_time = 1

            logger.info(f"Rate limited, waiting {wait_time:.1f}s")
            time.sleep(min(wait_time, 5))  # Check cancellation every 5s max
        return True

    @staticmethod
    def calculate_sha256(file_path: str) -> str:
        """
        Calculate SHA256 hash of a file using streaming for large files.

        Performance Note:
        - Reads file in 8KB chunks (buffered reading)
        - Memory efficient: constant ~8KB RAM usage regardless of file size
        - Can hash 650MB files (VT limit) without memory issues
        - Typical speed: ~500MB/s on SSD, ~100MB/s on HDD
        - Example: 100MB file takes ~0.2s on SSD

        Args:
            file_path: Path to the file.

        Returns:
            Lowercase hexadecimal SHA256 hash string.

        Raises:
            FileNotFoundError: If file doesn't exist.
            PermissionError: If file can't be read.
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest().lower()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> tuple[requests.Response | None, str | None]:
        """
        Make an API request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (appended to base URL)
            **kwargs: Additional arguments to pass to requests

        Returns:
            Tuple of (response, error_message). On success, error_message is None.
        """
        # ``endpoint`` may be an absolute URL (e.g. a one-time upload URL).
        url = endpoint if endpoint.startswith("http") else f"{VT_API_BASE}{endpoint}"
        session = self._get_session()

        for attempt in range(VT_MAX_RETRIES):
            if self._cancelled:
                return None, _("Scan cancelled")

            try:
                response = session.request(method, url, **kwargs)

                # Handle rate limiting from API
                if response.status_code == 429:
                    logger.warning("VirusTotal API rate limit hit")
                    return response, _("API rate limit exceeded")

                # Handle authentication errors
                if response.status_code == 401:
                    return response, _("Invalid API key")

                if response.status_code == 403:
                    return response, _("API key lacks required permissions")

                return response, None

            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{VT_MAX_RETRIES})")
                if attempt < VT_MAX_RETRIES - 1:
                    time.sleep(VT_RETRY_BASE_DELAY * (2**attempt))
                else:
                    return None, _("Request timed out after retries")

            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error (attempt {attempt + 1}/{VT_MAX_RETRIES})")
                if attempt < VT_MAX_RETRIES - 1:
                    time.sleep(VT_RETRY_BASE_DELAY * (2**attempt))
                else:
                    return None, _("Network connection failed after retries")

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {e}")
                return None, _("Request failed: {error}").format(error=e)

        return None, _("Unknown request error")

    def check_file_hash(self, sha256: str) -> VTScanResult:
        """
        Check if a file hash is known to VirusTotal.

        Args:
            sha256: SHA256 hash of the file.

        Returns:
            VTScanResult with scan results if known, or NOT_FOUND status.
        """
        if not self._wait_for_rate_limit():
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path="",
                sha256=sha256,
                error_message=_("Scan cancelled"),
            )

        response, error = self._make_request(
            "GET",
            f"/files/{sha256}",
            timeout=VT_REQUEST_TIMEOUT,
        )

        if error:
            if response and response.status_code == 429:
                return VTScanResult(
                    status=VTScanStatus.RATE_LIMITED,
                    file_path="",
                    sha256=sha256,
                    error_message=error,
                )
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path="",
                sha256=sha256,
                error_message=error,
            )

        if response is None:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path="",
                sha256=sha256,
                error_message=_("No response received"),
            )

        if response.status_code == 404:
            return VTScanResult(
                status=VTScanStatus.NOT_FOUND,
                file_path="",
                sha256=sha256,
            )

        if response.status_code != 200:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path="",
                sha256=sha256,
                error_message=_("API error: HTTP {code}").format(code=response.status_code),
            )

        try:
            data = response.json()
        except (ValueError, KeyError):
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path="",
                sha256=sha256,
                error_message=_("Invalid JSON response from API"),
            )
        return self._parse_file_report(data, sha256)

    def _parse_file_report(self, data: dict, sha256: str) -> VTScanResult:
        """
        Parse VirusTotal file report response.

        Args:
            data: JSON response from /files/{hash} endpoint.
            sha256: The file's SHA256 hash.

        Returns:
            VTScanResult with parsed scan results.
        """
        try:
            attrs = data.get("data", {}).get("attributes", {})
            if not attrs:
                return VTScanResult(
                    status=VTScanStatus.ERROR,
                    file_path="",
                    sha256=sha256,
                    error_message=_("Malformed response: missing report attributes"),
                )

            stats = attrs.get("last_analysis_stats", {})
            results = attrs.get("last_analysis_results", {})

            malicious = stats.get("malicious") or 0
            suspicious = stats.get("suspicious") or 0

            # The "X / Y" denominator must include every verdict bucket VT
            # reports (timeout, confirmed-timeout, failure, type-unsupported,
            # undetected, harmless, …), not just the four common ones — engines
            # that timed out or could not process the file still ran, and
            # omitting them silently undercounts total_engines on real reports.
            total = sum(v for v in stats.values() if isinstance(v, int) and not isinstance(v, bool))
            detections = malicious + suspicious

            # Parse individual engine detections
            detection_details = []
            for engine_name, engine_result in results.items():
                category = engine_result.get("category", "undetected")
                result = engine_result.get("result")
                # Only include engines that detected something
                if category in ("malicious", "suspicious"):
                    detection_details.append(
                        VTDetection(
                            engine_name=engine_name,
                            category=category,
                            result=result,
                        )
                    )

            # Determine status
            if detections > 0:
                status = VTScanStatus.DETECTED
            else:
                status = VTScanStatus.CLEAN

            # Parse scan date
            scan_timestamp = attrs.get("last_analysis_date")
            scan_date = None
            if scan_timestamp:
                try:
                    scan_date = datetime.fromtimestamp(scan_timestamp, tz=UTC).isoformat()
                except (ValueError, OSError) as e:
                    logger.debug("Invalid scan timestamp in VT response: %s", e)

            # Build permalink
            permalink = f"https://www.virustotal.com/gui/file/{sha256}"

            return VTScanResult(
                status=status,
                file_path="",
                sha256=sha256,
                detections=detections,
                total_engines=total,
                detection_details=detection_details,
                scan_date=scan_date,
                permalink=permalink,
            )

        except (KeyError, TypeError, AttributeError) as e:
            logger.error(f"Failed to parse VT response: {e}")
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path="",
                sha256=sha256,
                error_message=_("Failed to parse response: {error}").format(error=e),
            )

    def upload_file(self, file_path: str, sha256: str) -> VTScanResult:
        """
        Upload a file to VirusTotal for scanning.

        Args:
            file_path: Path to the file to upload.
            sha256: Pre-calculated SHA256 hash of the file.

        Returns:
            VTScanResult with scan results after upload completes.
        """
        if not self._wait_for_rate_limit():
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                sha256=sha256,
                error_message=_("Scan cancelled"),
            )

        try:
            with open(file_path, "rb") as f:
                # Read the bytes up front: requests consumes a file handle via
                # fp.read(), so reusing the same handle across _make_request's
                # retry loop would send an empty body on every attempt after the
                # first. Bytes re-encode correctly on each retry.
                data = f.read()
        except FileNotFoundError:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                sha256=sha256,
                error_message=_("File not found"),
            )
        except PermissionError:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                sha256=sha256,
                error_message=_("Permission denied"),
            )

        files = {"file": (os.path.basename(file_path), data)}

        if len(data) <= VT_DIRECT_UPLOAD_MAX:
            response, error = self._make_request(
                "POST",
                "/files",
                files=files,
                timeout=VT_UPLOAD_TIMEOUT,
            )
        else:
            # Files larger than the direct-upload limit must first obtain a
            # one-time upload URL, then POST the multipart body to it.
            url_response, url_error = self._make_request(
                "GET",
                "/files/upload_url",
                timeout=VT_REQUEST_TIMEOUT,
            )
            if url_error:
                if url_response is not None and url_response.status_code == 429:
                    return VTScanResult(
                        status=VTScanStatus.RATE_LIMITED,
                        file_path=file_path,
                        sha256=sha256,
                        error_message=url_error,
                    )
                return VTScanResult(
                    status=VTScanStatus.ERROR,
                    file_path=file_path,
                    sha256=sha256,
                    error_message=url_error,
                )

            try:
                upload_url = url_response.json().get("data") if url_response else None
            except (ValueError, AttributeError):
                upload_url = None

            if not isinstance(upload_url, str) or not upload_url:
                return VTScanResult(
                    status=VTScanStatus.ERROR,
                    file_path=file_path,
                    sha256=sha256,
                    error_message=_("Failed to obtain upload URL for large file"),
                )

            response, error = self._make_request(
                "POST",
                upload_url,
                files=files,
                timeout=VT_UPLOAD_TIMEOUT,
            )

        if error:
            if response and response.status_code == 429:
                return VTScanResult(
                    status=VTScanStatus.RATE_LIMITED,
                    file_path=file_path,
                    sha256=sha256,
                    error_message=error,
                )
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                sha256=sha256,
                error_message=error,
            )

        if response is None or response.status_code != 200:
            status_code = response.status_code if response else "N/A"
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                sha256=sha256,
                error_message=_("Upload failed: HTTP {code}").format(code=status_code),
            )

        # After upload, poll for results using the analysis ID
        try:
            upload_data = response.json()
            analysis_id = upload_data.get("data", {}).get("id")

            if analysis_id:
                return self._poll_analysis(analysis_id, file_path, sha256)
            else:
                # No analysis ID, try to get results by hash after a short delay
                time.sleep(5)
                return self.check_file_hash(sha256)

        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Failed to parse upload response: {e}")
            # Try to get results by hash anyway
            time.sleep(5)
            return self.check_file_hash(sha256)

    def _poll_analysis(
        self, analysis_id: str, file_path: str, sha256: str, max_wait: int = 120
    ) -> VTScanResult:
        """
        Poll for analysis completion.

        Args:
            analysis_id: VirusTotal analysis ID.
            file_path: Original file path.
            sha256: File SHA256 hash.
            max_wait: Maximum seconds to wait for completion.

        Returns:
            VTScanResult with final scan results.
        """
        start_time = time.time()
        poll_interval = 5  # seconds

        while time.time() - start_time < max_wait:
            if self._cancelled:
                return VTScanResult(
                    status=VTScanStatus.ERROR,
                    file_path=file_path,
                    sha256=sha256,
                    error_message=_("Scan cancelled"),
                )

            if not self._wait_for_rate_limit():
                return VTScanResult(
                    status=VTScanStatus.ERROR,
                    file_path=file_path,
                    sha256=sha256,
                    error_message=_("Scan cancelled"),
                )

            response, error = self._make_request(
                "GET",
                f"/analyses/{analysis_id}",
                timeout=VT_REQUEST_TIMEOUT,
            )

            if error:
                # On error during polling, try to get results by hash
                logger.warning(f"Poll error: {error}, trying hash lookup")
                return self.check_file_hash(sha256)

            if response and response.status_code == 200:
                try:
                    data = response.json()
                    status = data.get("data", {}).get("attributes", {}).get("status")

                    if status == "completed":
                        # Analysis complete, get full results
                        result = self.check_file_hash(sha256)
                        result.file_path = file_path
                        return result

                    elif status == "queued" or status == "running":
                        # Still processing
                        logger.debug(f"Analysis status: {status}")
                        time.sleep(poll_interval)
                        continue

                except (KeyError, TypeError, ValueError) as e:
                    logger.debug("Unexpected VT poll response structure: %s", e)

            time.sleep(poll_interval)

        # Timeout - try to get whatever results are available
        logger.warning("Analysis polling timeout, getting available results")
        result = self.check_file_hash(sha256)
        result.file_path = file_path
        if result.status == VTScanStatus.NOT_FOUND:
            result.status = VTScanStatus.PENDING
            result.error_message = _("Analysis still in progress")
        return result

    def scan_file_sync(self, file_path: str) -> VTScanResult:
        """
        Scan a file with VirusTotal (synchronous).

        This is the main scanning method that:
        1. Validates the file exists and is within size limits
        2. Calculates SHA256 hash
        3. Checks if hash is already known
        4. Uploads file if unknown
        5. Returns scan results

        Args:
            file_path: Path to the file to scan.

        Returns:
            VTScanResult with scan results.
        """
        start_time = time.time()
        self._cancelled = False

        # Validate API key
        if not self._api_key:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                error_message=_("API key not configured"),
            )

        # Validate file exists
        if not os.path.exists(file_path):
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                error_message=_("File not found"),
            )

        if not os.path.isfile(file_path):
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                error_message=_("Path is not a file"),
            )

        # Check file size
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                error_message=_("Cannot access file: {error}").format(error=e),
            )

        if file_size > VT_MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            return VTScanResult(
                status=VTScanStatus.FILE_TOO_LARGE,
                file_path=file_path,
                error_message=_("File too large ({size}MB). Maximum size is {max}MB").format(
                    size=f"{size_mb:.1f}", max=VT_MAX_FILE_SIZE // (1024 * 1024)
                ),
            )

        if file_size == 0:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                error_message=_("Cannot scan empty files"),
            )

        # Calculate SHA256
        logger.info(f"Calculating SHA256 for {file_path}")
        try:
            sha256 = self.calculate_sha256(file_path)
        except (OSError, PermissionError) as e:
            return VTScanResult(
                status=VTScanStatus.ERROR,
                file_path=file_path,
                error_message=_("Cannot read file: {error}").format(error=e),
            )

        logger.info(f"SHA256: {sha256}")

        # Upload vs Hash Lookup Decision Logic:
        # 1. Always check hash first (fast, ~1s API call)
        # 2. If hash is known (status != NOT_FOUND):
        #    - Return existing results immediately (no upload needed)
        #    - Saves API quota and time
        #    - Typical for known malware (seen by VT before)
        # 3. If hash is unknown (status == NOT_FOUND):
        #    - File is new to VirusTotal
        #    - Upload file for analysis (slow, ~10-60s depending on size)
        #    - Poll for results every 5 seconds
        #    - Return results when analysis completes
        #
        # Why hash-first strategy:
        # - 650MB upload can take minutes on slow connections
        # - Most malware has known signatures already in VT database
        # - Hash lookup only uses 1 API request vs upload (uses 2-4 requests)
        # Check if hash is known
        logger.info("Checking if file is known to VirusTotal")
        result = self.check_file_hash(sha256)
        result.file_path = file_path

        if result.status == VTScanStatus.NOT_FOUND:
            # File not known, upload it
            logger.info("File not known, uploading to VirusTotal")
            result = self.upload_file(file_path, sha256)
            result.file_path = file_path

        result.duration = time.time() - start_time
        return result

    def scan_file_async(
        self,
        file_path: str,
        callback: Callable[[VTScanResult], None],
    ) -> None:
        """
        Scan a file with VirusTotal (asynchronous).

        Runs the scan in a background thread and calls the callback
        on the GTK main thread using GLib.idle_add.

        Args:
            file_path: Path to the file to scan.
            callback: Function to call with VTScanResult when complete.
        """

        def scan_thread():
            result = self.scan_file_sync(file_path)
            try:
                from gi.repository import GLib

                GLib.idle_add(callback, result)
            except ImportError:
                # If GLib not available, call directly (for testing)
                callback(result)

        thread = threading.Thread(target=scan_thread, daemon=True)
        thread.start()

    def close(self) -> None:
        """Close the client and release resources."""
        if self._session:
            self._session.close()
            self._session = None
