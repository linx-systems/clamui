# ClamUI Portmaster Client Tests
"""Unit tests for the optional Portmaster API client.

The detection chain must produce one of four discrete statuses without
raising, and probe_portmaster must never surface a FAIL/WARNING flag to
the audit when Portmaster is simply absent.
"""

from unittest.mock import MagicMock, patch

import requests

from src.core.portmaster_client import (
    PortmasterStatus,
    _parse_modules_status,
    probe_portmaster,
    request_app_token,
)


class TestProbePortmaster:
    @patch("src.core.portmaster_client._ping", return_value=True)
    def test_ping_succeeds_returns_running(self, mock_ping):
        result = probe_portmaster()
        assert result.status == PortmasterStatus.RUNNING
        assert result.module_status is None  # No token => no module fetch.

    @patch("src.core.portmaster_client._binary_or_service_present", return_value=True)
    @patch("src.core.portmaster_client._ping", return_value=False)
    def test_ping_fails_but_binary_present_is_installed_not_running(self, mock_ping, mock_present):
        result = probe_portmaster()
        assert result.status == PortmasterStatus.INSTALLED_NOT_RUNNING

    @patch("src.core.portmaster_client._binary_or_service_present", return_value=False)
    @patch("src.core.portmaster_client._ping", return_value=False)
    def test_ping_fails_and_no_binary_is_not_installed(self, mock_ping, mock_present):
        result = probe_portmaster()
        assert result.status == PortmasterStatus.NOT_INSTALLED

    @patch("src.core.portmaster_client._fetch_modules_status")
    @patch("src.core.portmaster_client._ping", return_value=True)
    def test_running_with_token_fetches_module_status(self, mock_ping, mock_fetch):
        mock_fetch.return_value = ({"core": {"Status": "online"}}, False, None)
        result = probe_portmaster(token="secret")
        assert result.status == PortmasterStatus.RUNNING
        assert result.module_status == {"core": {"Status": "online"}}
        assert len(result.module_rows) == 1
        assert result.module_rows[0].name == "core"

    @patch("src.core.portmaster_client._fetch_modules_status")
    @patch("src.core.portmaster_client._ping", return_value=True)
    def test_401_sets_unauthorized_flag(self, mock_ping, mock_fetch):
        mock_fetch.return_value = (None, True, "Token rejected (401)")
        result = probe_portmaster(token="stale")
        assert result.status == PortmasterStatus.RUNNING
        assert result.modules_unauthorized is True
        assert result.module_status is None

    @patch("src.core.portmaster_client._ping", side_effect=Exception("boom"))
    def test_unexpected_exception_returns_error(self, mock_ping):
        result = probe_portmaster()
        assert result.status == PortmasterStatus.ERROR
        assert result.error == "boom"


class TestPingHelper:
    @patch("src.core.portmaster_client.requests.get")
    def test_ping_recognises_pong(self, mock_get):
        from src.core.portmaster_client import _ping

        mock_get.return_value = MagicMock(status_code=200, text="Pong")
        assert _ping() is True

    @patch(
        "src.core.portmaster_client.requests.get",
        side_effect=requests.exceptions.ConnectionError(),
    )
    def test_ping_swallows_connection_error(self, mock_get):
        from src.core.portmaster_client import _ping

        assert _ping() is False

    @patch(
        "src.core.portmaster_client.requests.get",
        side_effect=requests.exceptions.Timeout(),
    )
    def test_ping_swallows_timeout(self, mock_get):
        from src.core.portmaster_client import _ping

        assert _ping() is False


class TestParseModulesStatus:
    def test_handles_non_dict_payload(self):
        assert _parse_modules_status("garbage") == []
        assert _parse_modules_status(None) == []
        assert _parse_modules_status([1, 2, 3]) == []

    def test_extracts_status_and_failure(self):
        rows = _parse_modules_status(
            {
                "core": {"Status": "online"},
                "filter": {"status": "error", "failure_msg": "boom"},
            }
        )
        names = [r.name for r in rows]
        assert names == ["core", "filter"]  # Sorted alphabetically.
        filter_row = next(r for r in rows if r.name == "filter")
        assert filter_row.status == "error"
        assert filter_row.failure_msg == "boom"


class TestRequestAppToken:
    @patch("src.core.portmaster_client.requests.get")
    def test_returns_token_on_200(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"token": "abc"},
        )
        token, err = request_app_token()
        assert token == "abc"
        assert err is None

    @patch("src.core.portmaster_client.requests.get")
    def test_user_decline_returns_silent_none(self, mock_get):
        # 401/403 is the expected silent-fail path, not an "error".
        mock_get.return_value = MagicMock(status_code=403)
        token, err = request_app_token()
        assert token is None
        assert err is None

    @patch(
        "src.core.portmaster_client.requests.get",
        side_effect=requests.exceptions.Timeout(),
    )
    def test_timeout_is_explicit_error(self, mock_get):
        token, err = request_app_token()
        assert token is None
        assert err == "Authorization request timed out"

    @patch("src.core.portmaster_client.requests.get")
    def test_plain_text_response_is_used_as_token(self, mock_get):
        # Some Portmaster builds return text/plain; ValueError on .json().
        def _raise_value_error():
            raise ValueError("no json")

        mock_get.return_value = MagicMock(
            status_code=200,
            json=_raise_value_error,
            text="raw-token\n",
        )
        token, err = request_app_token()
        assert token == "raw-token"
        assert err is None
