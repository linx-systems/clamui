# ClamUI VirusTotal Client Tests
"""Unit tests for the VirusTotal API client."""

import hashlib
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from src.core.virustotal import (
    VT_MAX_FILE_SIZE,
    VT_RATE_LIMIT_REQUESTS,
    VirusTotalClient,
    VTDetection,
    VTScanResult,
    VTScanStatus,
)


class TestVTScanResult:
    """Tests for VTScanResult dataclass."""

    def test_is_clean_for_clean_status(self):
        """Test is_clean property for clean status."""
        result = VTScanResult(status=VTScanStatus.CLEAN, file_path="/test")
        assert result.is_clean is True

    def test_is_clean_for_not_found(self):
        """Test is_clean property for not found status."""
        result = VTScanResult(status=VTScanStatus.NOT_FOUND, file_path="/test")
        assert result.is_clean is True

    def test_is_clean_for_detected(self):
        """Test is_clean property for detected status."""
        result = VTScanResult(status=VTScanStatus.DETECTED, file_path="/test")
        assert result.is_clean is False

    def test_has_threats_for_detected(self):
        """Test has_threats property for detected status."""
        result = VTScanResult(status=VTScanStatus.DETECTED, file_path="/test")
        assert result.has_threats is True

    def test_has_threats_for_clean(self):
        """Test has_threats property for clean status."""
        result = VTScanResult(status=VTScanStatus.CLEAN, file_path="/test")
        assert result.has_threats is False

    def test_is_error_for_error_status(self):
        """Test is_error property for various error statuses."""
        for status in [VTScanStatus.ERROR, VTScanStatus.RATE_LIMITED, VTScanStatus.FILE_TOO_LARGE]:
            result = VTScanResult(status=status, file_path="/test")
            assert result.is_error is True

    def test_is_error_for_non_error_status(self):
        """Test is_error property for non-error statuses."""
        for status in [VTScanStatus.CLEAN, VTScanStatus.DETECTED, VTScanStatus.NOT_FOUND]:
            result = VTScanResult(status=status, file_path="/test")
            assert result.is_error is False


class TestVirusTotalClientInit:
    """Tests for VirusTotalClient initialization."""

    def test_init_with_api_key(self):
        """Test client initialization with API key."""
        client = VirusTotalClient(api_key="test_key")
        assert client._api_key == "test_key"

    def test_init_without_api_key(self):
        """Test client initialization without API key."""
        client = VirusTotalClient()
        assert client._api_key is None

    def test_set_api_key(self):
        """Test setting API key after initialization."""
        client = VirusTotalClient()
        client.set_api_key("new_key")
        assert client._api_key == "new_key"


class TestCalculateSha256:
    """Tests for SHA256 calculation."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file with known content."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()
            yield f.name
        Path(f.name).unlink(missing_ok=True)

    def test_calculate_sha256(self, temp_file):
        """Test SHA256 calculation for a file."""
        expected_hash = hashlib.sha256(b"test content").hexdigest().lower()
        result = VirusTotalClient.calculate_sha256(temp_file)
        assert result == expected_hash

    def test_calculate_sha256_file_not_found(self):
        """Test SHA256 calculation for non-existent file."""
        with pytest.raises(FileNotFoundError):
            VirusTotalClient.calculate_sha256("/nonexistent/file")


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_check_rate_limit_allows_initial_requests(self):
        """Test that initial requests are allowed."""
        client = VirusTotalClient(api_key="test")
        for _ in range(VT_RATE_LIMIT_REQUESTS):
            assert client._check_rate_limit() is True

    def test_check_rate_limit_blocks_excess_requests(self):
        """Test that excess requests are blocked."""
        client = VirusTotalClient(api_key="test")
        # Fill up the rate limit
        for _ in range(VT_RATE_LIMIT_REQUESTS):
            client._check_rate_limit()

        # Next request should be blocked
        assert client._check_rate_limit() is False


class TestScanFileSyncValidation:
    """Tests for scan_file_sync input validation."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key_" + "a" * 50)

    def test_scan_without_api_key(self):
        """Test that scanning without API key returns error."""
        client = VirusTotalClient()
        result = client.scan_file_sync("/some/file")
        assert result.status == VTScanStatus.ERROR
        assert "API key" in result.error_message

    def test_scan_nonexistent_file(self, client):
        """Test scanning a non-existent file."""
        result = client.scan_file_sync("/nonexistent/file/path")
        assert result.status == VTScanStatus.ERROR
        assert "not found" in result.error_message.lower()

    def test_scan_directory(self, client, tmp_path):
        """Test that scanning a directory returns error."""
        result = client.scan_file_sync(str(tmp_path))
        assert result.status == VTScanStatus.ERROR
        assert "not a file" in result.error_message.lower()

    def test_scan_empty_file(self, client, tmp_path):
        """Test that scanning an empty file returns error."""
        empty_file = tmp_path / "empty.txt"
        empty_file.touch()

        result = client.scan_file_sync(str(empty_file))
        assert result.status == VTScanStatus.ERROR
        assert "empty" in result.error_message.lower()

    def test_scan_file_too_large(self, client, tmp_path):
        """Test that files exceeding size limit return error."""
        # Mock os.path.getsize to return a large size
        large_file = tmp_path / "large.bin"
        large_file.write_bytes(b"x")

        with mock.patch("os.path.getsize", return_value=VT_MAX_FILE_SIZE + 1):
            result = client.scan_file_sync(str(large_file))

        assert result.status == VTScanStatus.FILE_TOO_LARGE


class TestCheckFileHash:
    """Tests for hash checking functionality."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key_" + "a" * 50)

    def test_check_hash_clean_file(self, client):
        """Test checking a clean file hash."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "suspicious": 0,
                        "undetected": 70,
                        "harmless": 0,
                    },
                    "last_analysis_results": {},
                    "last_analysis_date": 1704067200,
                }
            }
        }

        with mock.patch.object(client, "_make_request", return_value=(mock_response, None)):
            # Bypass rate limiting
            client._request_times = []

            result = client.check_file_hash("a" * 64)

        assert result.status == VTScanStatus.CLEAN
        assert result.total_engines == 70

    def test_check_hash_detected_file(self, client):
        """Test checking a detected file hash."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "suspicious": 2,
                        "undetected": 63,
                        "harmless": 0,
                    },
                    "last_analysis_results": {
                        "EngineA": {"category": "malicious", "result": "Trojan.Gen"},
                        "EngineB": {"category": "suspicious", "result": "PUP.Generic"},
                    },
                    "last_analysis_date": 1704067200,
                }
            }
        }

        with mock.patch.object(client, "_make_request", return_value=(mock_response, None)):
            client._request_times = []

            result = client.check_file_hash("b" * 64)

        assert result.status == VTScanStatus.DETECTED
        assert result.detections == 7
        assert len(result.detection_details) == 2

    def test_check_hash_not_found(self, client):
        """Test checking an unknown file hash."""
        mock_response = mock.Mock()
        mock_response.status_code = 404

        with mock.patch.object(client, "_make_request", return_value=(mock_response, None)):
            client._request_times = []

            result = client.check_file_hash("c" * 64)

        assert result.status == VTScanStatus.NOT_FOUND

    def test_check_hash_rate_limited(self, client):
        """Test handling rate limit response."""
        mock_response = mock.Mock()
        mock_response.status_code = 429

        with mock.patch.object(
            client, "_make_request", return_value=(mock_response, "API rate limit exceeded")
        ):
            client._request_times = []

            result = client.check_file_hash("d" * 64)

        assert result.status == VTScanStatus.RATE_LIMITED


class TestParseFileReport:
    """Tests for parsing VirusTotal API responses."""

    @pytest.fixture
    def client(self):
        """Create a client instance."""
        return VirusTotalClient(api_key="test")

    def test_parse_clean_report(self, client):
        """Test parsing a clean file report."""
        data = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "suspicious": 0,
                        "undetected": 72,
                        "harmless": 0,
                    },
                    "last_analysis_results": {},
                    "last_analysis_date": 1704067200,
                }
            }
        }

        result = client._parse_file_report(data, "test_hash")

        assert result.status == VTScanStatus.CLEAN
        assert result.detections == 0
        assert result.total_engines == 72
        assert result.permalink == "https://www.virustotal.com/gui/file/test_hash"

    def test_parse_detected_report(self, client):
        """Test parsing a report with detections."""
        data = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 10,
                        "suspicious": 5,
                        "undetected": 55,
                        "harmless": 0,
                    },
                    "last_analysis_results": {
                        "Avast": {"category": "malicious", "result": "Win32:Malware-gen"},
                        "Kaspersky": {"category": "malicious", "result": "Trojan.Win32.Generic"},
                        "Clean": {"category": "undetected", "result": None},
                    },
                }
            }
        }

        result = client._parse_file_report(data, "test_hash")

        assert result.status == VTScanStatus.DETECTED
        assert result.detections == 15
        assert len(result.detection_details) == 2  # Only malicious/suspicious

    def test_parse_malformed_report(self, client):
        """Test parsing a malformed report returns ERROR, not a false CLEAN."""
        data = {"invalid": "data"}

        result = client._parse_file_report(data, "test_hash")

        # Malformed response with no data.attributes should be ERROR,
        # not silently CLEAN (which would be a dangerous false negative)
        assert result.status == VTScanStatus.ERROR
        assert result.error_message is not None
        assert (
            "malformed" in result.error_message.lower() or "missing" in result.error_message.lower()
        )

    def test_parse_report_non_dict_engine_result_returns_error(self, client):
        """A non-dict value in last_analysis_results must yield ERROR, not crash.

        Regression: the detection loop called .get() on each engine result; a null
        (or otherwise non-dict) value raised AttributeError, which escaped the
        (KeyError, TypeError) handler. In scan_file_async that killed the worker
        thread so the completion callback never fired and the UI hung. The handler
        now also catches AttributeError and returns a clean ERROR result.
        """
        data = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 1, "undetected": 5},
                    "last_analysis_results": {"BrokenEngine": None},
                }
            }
        }

        result = client._parse_file_report(data, "test_hash")

        assert result.status == VTScanStatus.ERROR
        assert result.error_message is not None

    def test_parse_total_engines_includes_all_buckets(self, client):
        """total_engines must count timeout/failure/type-unsupported engines too.
        Real VT reports include engines that timed out or could not process the
        file. Omitting those buckets undercounts the "X / Y" denominator shown
        to the user.
        """
        data = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 3,
                        "suspicious": 1,
                        "undetected": 60,
                        "harmless": 0,
                        "timeout": 4,
                        "confirmed-timeout": 1,
                        "failure": 2,
                        "type-unsupported": 5,
                    },
                    "last_analysis_results": {},
                }
            }
        }

        result = client._parse_file_report(data, "test_hash")

        assert result.status == VTScanStatus.DETECTED
        assert result.detections == 4
        # 3 + 1 + 60 + 0 + 4 + 1 + 2 + 5 = 76, not just the four common buckets (64).
        assert result.total_engines == 76


class TestVTDetection:
    """Tests for VTDetection dataclass."""

    def test_detection_creation(self):
        """Test creating a VTDetection instance."""
        detection = VTDetection(
            engine_name="TestEngine", category="malicious", result="Trojan.Generic"
        )

        assert detection.engine_name == "TestEngine"
        assert detection.category == "malicious"
        assert detection.result == "Trojan.Generic"

    def test_detection_with_none_result(self):
        """Test creating a VTDetection with None result."""
        detection = VTDetection(engine_name="TestEngine", category="undetected", result=None)

        assert detection.result is None


class TestCancel:
    """Tests for scan cancellation."""

    def test_cancel_sets_flag(self):
        """Test that cancel sets the cancelled flag."""
        client = VirusTotalClient(api_key="test")
        assert client._cancelled is False

        client.cancel()

        assert client._cancelled is True

    def test_scan_file_sync_resets_cancel_flag(self):
        """Test that scan_file_sync resets the cancel flag."""
        client = VirusTotalClient()  # No API key to trigger early return
        client._cancelled = True

        client.scan_file_sync("/test")

        assert client._cancelled is False


class TestClose:
    """Tests for client cleanup."""

    def test_close_releases_session(self):
        """Test that close releases the session."""
        client = VirusTotalClient(api_key="test")
        # Force session creation
        client._get_session()
        assert client._session is not None

        client.close()

        assert client._session is None


class TestMakeRequest:
    """Tests for _make_request method."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key")

    def test_make_request_cancelled(self, client):
        """Test _make_request returns early when cancelled."""
        client._cancelled = True

        response, error = client._make_request("GET", "/files/abc")

        assert response is None
        assert "cancelled" in error.lower()

    def test_make_request_auth_error(self, client):
        """Test _make_request handles 401 auth error."""
        mock_response = mock.Mock()
        mock_response.status_code = 401

        with mock.patch.object(client._get_session(), "request", return_value=mock_response):
            response, error = client._make_request("GET", "/files/abc")

        assert error == "Invalid API key"

    def test_make_request_forbidden(self, client):
        """Test _make_request handles 403 forbidden."""
        mock_response = mock.Mock()
        mock_response.status_code = 403

        with mock.patch.object(client._get_session(), "request", return_value=mock_response):
            response, error = client._make_request("GET", "/files/abc")

        assert "permissions" in error.lower()

    def test_make_request_timeout_retries(self, client):
        """Test _make_request retries on timeout."""
        import requests

        with mock.patch.object(
            client._get_session(),
            "request",
            side_effect=requests.exceptions.Timeout("timeout"),
        ):
            with mock.patch("time.sleep"):  # Don't actually sleep
                response, error = client._make_request("GET", "/files/abc")

        assert response is None
        assert "timed out" in error.lower()

    def test_make_request_connection_error_retries(self, client):
        """Test _make_request retries on connection error."""
        import requests

        with mock.patch.object(
            client._get_session(),
            "request",
            side_effect=requests.exceptions.ConnectionError("network"),
        ):
            with mock.patch("time.sleep"):  # Don't actually sleep
                response, error = client._make_request("GET", "/files/abc")

        assert response is None
        assert "connection failed" in error.lower()

    def test_make_request_general_exception(self, client):
        """Test _make_request handles general request exceptions."""
        import requests

        with mock.patch.object(
            client._get_session(),
            "request",
            side_effect=requests.exceptions.RequestException("error"),
        ):
            response, error = client._make_request("GET", "/files/abc")

        assert response is None
        assert "failed" in error.lower()


class TestUploadFile:
    """Tests for upload_file method."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key_" + "a" * 50)

    def test_upload_file_not_found(self, client):
        """Test upload_file with non-existent file."""
        client._request_times = []  # Bypass rate limiting

        result = client.upload_file("/nonexistent/file", "a" * 64)

        assert result.status == VTScanStatus.ERROR
        assert "not found" in result.error_message.lower()

    def test_upload_file_cancelled(self, client, tmp_path):
        """Test upload_file returns early when cancelled."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        client._cancelled = True

        result = client.upload_file(str(test_file), "a" * 64)

        assert result.status == VTScanStatus.ERROR
        assert "cancelled" in result.error_message.lower()

    def test_upload_file_success(self, client, tmp_path):
        """Test successful file upload."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        sha256 = "a" * 64

        # Mock response for upload
        mock_upload_response = mock.Mock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {"data": {"id": "analysis_123"}}

        # Mock response for analysis polling
        mock_poll_response = mock.Mock()
        mock_poll_response.status_code = 200
        mock_poll_response.json.return_value = {"data": {"attributes": {"status": "completed"}}}

        # Mock response for hash check
        mock_hash_response = mock.Mock()
        mock_hash_response.status_code = 200
        mock_hash_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "suspicious": 0,
                        "undetected": 70,
                        "harmless": 0,
                    },
                    "last_analysis_results": {},
                }
            }
        }

        client._request_times = []  # Bypass rate limiting

        with mock.patch.object(
            client,
            "_make_request",
            side_effect=[
                (mock_upload_response, None),
                (mock_poll_response, None),
                (mock_hash_response, None),
            ],
        ):
            result = client.upload_file(str(test_file), sha256)

        assert result.status == VTScanStatus.CLEAN

    def test_upload_file_retry_sends_full_bytes(self, client, tmp_path):
        """Retries must re-send the full file body, not an exhausted handle."""
        import requests

        test_file = tmp_path / "test.txt"
        content = b"hello virustotal payload content"
        test_file.write_bytes(content)
        client._request_times = []  # Bypass rate limiting

        success = mock.Mock()
        success.status_code = 200
        success.json.return_value = {"data": {"id": "analysis_123"}}

        seen_files = []

        def fake_request(method, url, **kwargs):
            seen_files.append(kwargs.get("files"))
            if len(seen_files) == 1:
                raise requests.exceptions.Timeout("boom")
            return success

        poll_result = VTScanResult(
            status=VTScanStatus.CLEAN, file_path=str(test_file), sha256="a" * 64
        )

        with (
            mock.patch.object(client._get_session(), "request", side_effect=fake_request),
            mock.patch("time.sleep"),
            mock.patch.object(client, "_poll_analysis", return_value=poll_result),
        ):
            result = client.upload_file(str(test_file), "a" * 64)

        # Timeout on attempt 1, success on attempt 2.
        assert len(seen_files) == 2
        file_part = seen_files[1]["file"]
        # The retry must carry the complete file as bytes, not a spent handle.
        assert isinstance(file_part[1], bytes)
        assert file_part[1] == content
        assert result.status == VTScanStatus.CLEAN

    def test_upload_file_small_posts_files_directly(self, client, tmp_path):
        """Files <= the direct-upload limit POST straight to /files."""
        test_file = tmp_path / "small.txt"
        test_file.write_bytes(b"tiny")
        client._request_times = []

        upload_resp = mock.Mock()
        upload_resp.status_code = 200
        upload_resp.json.return_value = {"data": {"id": "analysis_1"}}
        poll_result = VTScanResult(
            status=VTScanStatus.CLEAN, file_path=str(test_file), sha256="a" * 64
        )

        with (
            mock.patch.object(client, "_make_request", side_effect=[(upload_resp, None)]) as mreq,
            mock.patch.object(client, "_poll_analysis", return_value=poll_result),
        ):
            client.upload_file(str(test_file), "a" * 64)

        assert mreq.call_count == 1
        assert mreq.call_args_list[0].args[0] == "POST"
        assert mreq.call_args_list[0].args[1] == "/files"

    def test_upload_file_large_uses_upload_url(self, client, tmp_path):
        """Files > the direct-upload limit GET an upload URL then POST to it."""
        test_file = tmp_path / "big.bin"
        test_file.write_bytes(b"x" * 100)
        client._request_times = []

        one_time_url = "https://upload.virustotal.com/one-time-url"
        url_resp = mock.Mock()
        url_resp.status_code = 200
        url_resp.json.return_value = {"data": one_time_url}

        upload_resp = mock.Mock()
        upload_resp.status_code = 200
        upload_resp.json.return_value = {"data": {"id": "analysis_456"}}

        poll_result = VTScanResult(
            status=VTScanStatus.CLEAN, file_path=str(test_file), sha256="a" * 64
        )

        with (
            mock.patch("src.core.virustotal.VT_DIRECT_UPLOAD_MAX", 4),
            mock.patch.object(
                client,
                "_make_request",
                side_effect=[(url_resp, None), (upload_resp, None)],
            ) as mreq,
            mock.patch.object(client, "_poll_analysis", return_value=poll_result),
        ):
            result = client.upload_file(str(test_file), "a" * 64)

        assert mreq.call_count == 2
        assert mreq.call_args_list[0].args[0] == "GET"
        assert mreq.call_args_list[0].args[1] == "/files/upload_url"
        assert mreq.call_args_list[1].args[0] == "POST"
        assert mreq.call_args_list[1].args[1] == one_time_url
        assert result.status == VTScanStatus.CLEAN

    def test_upload_file_large_missing_upload_url(self, client, tmp_path):
        """A missing/invalid upload URL yields an ERROR result, not a crash."""
        test_file = tmp_path / "big.bin"
        test_file.write_bytes(b"x" * 100)
        client._request_times = []

        url_resp = mock.Mock()
        url_resp.status_code = 200
        url_resp.json.return_value = {"data": None}

        with (
            mock.patch("src.core.virustotal.VT_DIRECT_UPLOAD_MAX", 4),
            mock.patch.object(client, "_make_request", return_value=(url_resp, None)),
        ):
            result = client.upload_file(str(test_file), "a" * 64)

        assert result.status == VTScanStatus.ERROR


class TestWaitForRateLimit:
    """Tests for _wait_for_rate_limit method."""

    def test_wait_for_rate_limit_cancelled(self):
        """Test _wait_for_rate_limit returns False when cancelled."""
        client = VirusTotalClient(api_key="test")
        # Fill up rate limit
        client._request_times = [time.time() for _ in range(VT_RATE_LIMIT_REQUESTS)]
        client._cancelled = True

        result = client._wait_for_rate_limit()

        assert result is False


class TestPollAnalysis:
    """Tests for _poll_analysis method."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key")

    def test_poll_analysis_cancelled(self, client):
        """Test _poll_analysis returns early when cancelled."""
        client._cancelled = True

        result = client._poll_analysis("analysis_123", "/test/file", "a" * 64)

        assert result.status == VTScanStatus.ERROR
        assert "cancelled" in result.error_message.lower()

    def test_poll_analysis_queued(self, client):
        """Test _poll_analysis waits when status is queued."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"attributes": {"status": "queued"}}}

        # After a few polls, return completed
        mock_complete_response = mock.Mock()
        mock_complete_response.status_code = 200
        mock_complete_response.json.return_value = {"data": {"attributes": {"status": "completed"}}}

        mock_hash_response = mock.Mock()
        mock_hash_response.status_code = 200
        mock_hash_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "suspicious": 0,
                        "undetected": 70,
                        "harmless": 0,
                    },
                    "last_analysis_results": {},
                }
            }
        }

        client._request_times = []  # Bypass rate limiting

        with mock.patch.object(
            client,
            "_make_request",
            side_effect=[
                (mock_response, None),
                (mock_complete_response, None),
                (mock_hash_response, None),
            ],
        ):
            with mock.patch("time.sleep"):  # Don't actually sleep
                with mock.patch("time.time", side_effect=[0, 0, 0, 5, 5, 5, 10, 10, 10]):
                    result = client._poll_analysis("analysis_123", "/test/file", "a" * 64)

        assert result.status == VTScanStatus.CLEAN


class TestScanFileAsync:
    """Tests for scan_file_async method."""

    def test_scan_file_async_calls_callback(self):
        """Test scan_file_async runs scan and calls callback."""
        import threading

        client = VirusTotalClient()  # No API key to get quick error result
        results = []
        event = threading.Event()

        def callback(result):
            results.append(result)
            event.set()

        # Mock GLib to avoid import errors
        with mock.patch.dict(
            "sys.modules", {"gi": mock.MagicMock(), "gi.repository": mock.MagicMock()}
        ):
            # Mock GLib.idle_add to call the callback directly
            mock_glib = mock.MagicMock()
            mock_glib.idle_add = lambda fn, *args: fn(*args)
            with mock.patch.dict("sys.modules", {"gi.repository": mock.MagicMock(GLib=mock_glib)}):
                client.scan_file_async("/test/file", callback)

                # Wait for thread to complete (with timeout)
                event.wait(timeout=5.0)

        assert len(results) == 1
        assert results[0].status == VTScanStatus.ERROR


class TestSetApiKey:
    """Tests for set_api_key method."""

    def test_set_api_key_resets_session(self):
        """Test set_api_key resets session when key changes."""
        client = VirusTotalClient(api_key="old_key")
        # Force session creation
        client._get_session()
        assert client._session is not None

        client.set_api_key("new_key")

        assert client._session is None
        assert client._api_key == "new_key"


class TestCheckFileHashErrors:
    """Tests for error handling in check_file_hash."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key")

    def test_check_hash_api_error(self, client):
        """Test check_file_hash handles unexpected HTTP status."""
        mock_response = mock.Mock()
        mock_response.status_code = 500

        client._request_times = []  # Bypass rate limiting

        with mock.patch.object(client, "_make_request", return_value=(mock_response, None)):
            result = client.check_file_hash("a" * 64)

        assert result.status == VTScanStatus.ERROR
        assert "HTTP 500" in result.error_message

    def test_check_hash_no_response(self, client):
        """Test check_file_hash handles None response."""
        client._request_times = []  # Bypass rate limiting

        with mock.patch.object(client, "_make_request", return_value=(None, None)):
            result = client.check_file_hash("a" * 64)

        assert result.status == VTScanStatus.ERROR
        assert "no response" in result.error_message.lower()

    def test_check_hash_request_error(self, client):
        """Test check_file_hash handles request error."""
        client._request_times = []  # Bypass rate limiting

        with mock.patch.object(client, "_make_request", return_value=(None, "Connection failed")):
            result = client.check_file_hash("a" * 64)

        assert result.status == VTScanStatus.ERROR
        assert "Connection failed" in result.error_message


class TestScanFileSyncCoverage:
    """Additional tests for scan_file_sync to cover edge cases."""

    @pytest.fixture
    def client(self):
        """Create a client with API key."""
        return VirusTotalClient(api_key="test_api_key")

    def test_scan_file_hash_error(self, client, tmp_path):
        """Test scan_file_sync handles hash calculation error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with mock.patch.object(
            VirusTotalClient,
            "calculate_sha256",
            side_effect=PermissionError("denied"),
        ):
            result = client.scan_file_sync(str(test_file))

        assert result.status == VTScanStatus.ERROR
        assert "cannot read" in result.error_message.lower()

    def test_scan_file_size_error(self, client, tmp_path):
        """Test scan_file_sync handles file size access error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with mock.patch("os.path.getsize", side_effect=OSError("size error")):
            result = client.scan_file_sync(str(test_file))

        assert result.status == VTScanStatus.ERROR
        assert "cannot access" in result.error_message.lower()
