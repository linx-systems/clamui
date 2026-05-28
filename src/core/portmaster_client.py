# ClamUI Portmaster Integration Module
"""
Portmaster (https://safing.io) developer-API client for the security audit.

Implements an optional, fully silent-when-absent integration with Portmaster's
HTTP API at http://127.0.0.1:817. Used by `system_audit.check_portmaster` to
decide whether Portmaster is RUNNING, INSTALLED_NOT_RUNNING, or NOT_INSTALLED
without raising any audit flags when the service simply isn't present.

Detection chain (in order):
1. GET /api/v1/ping  — unauthenticated liveness probe. "Pong" => RUNNING.
2. On ConnectionError: probe `portmaster-start` binary and `portmaster.service`
   to distinguish INSTALLED_NOT_RUNNING from NOT_INSTALLED.

When a token is supplied (User-privilege endpoints), GET /api/v1/modules/status
is fetched for richer per-module health rows. A 401 response clears the stale
token from the keyring so the user is reprompted to re-authorize.

The token itself is acquired via GET /api/v1/app/auth which prompts the user
inside Portmaster's own UI — no manual key paste required.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import requests

logger = logging.getLogger(__name__)

PORTMASTER_API_BASE = "http://127.0.0.1:817/api/v1"
PORTMASTER_PROBE_TIMEOUT = 1.5
PORTMASTER_AUTHED_TIMEOUT = 5.0
PORTMASTER_AUTH_TIMEOUT = 60.0  # /app/auth blocks on user interaction


class PortmasterStatus(Enum):
    RUNNING = "running"
    INSTALLED_NOT_RUNNING = "installed_not_running"
    NOT_INSTALLED = "not_installed"
    ERROR = "error"


@dataclass
class PortmasterProbeResult:
    status: PortmasterStatus
    module_status: dict[str, Any] | None = None
    error: str | None = None
    modules_unauthorized: bool = False
    module_rows: list[PortmasterModuleRow] = field(default_factory=list)


@dataclass
class PortmasterModuleRow:
    name: str
    status: str
    failure_msg: str | None = None


def _ping(timeout: float = PORTMASTER_PROBE_TIMEOUT) -> bool:
    """Return True if Portmaster's /ping endpoint responds with Pong."""
    try:
        resp = requests.get(f"{PORTMASTER_API_BASE}/ping", timeout=timeout)
    except requests.exceptions.RequestException:
        return False
    return resp.status_code == 200 and "Pong" in resp.text


def _binary_or_service_present() -> bool:
    """Return True if portmaster-start binary or portmaster.service unit exists."""
    from .flatpak import get_clean_env, wrap_host_command

    try:
        rc = subprocess.run(
            wrap_host_command(["which", "portmaster-start"]),
            capture_output=True,
            timeout=5,
            env=get_clean_env(),
        ).returncode
        if rc == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("which portmaster-start failed: %s", e)

    try:
        rc = subprocess.run(
            wrap_host_command(["systemctl", "cat", "portmaster.service"]),
            capture_output=True,
            timeout=5,
            env=get_clean_env(),
        ).returncode
        return rc == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("systemctl cat portmaster.service failed: %s", e)
        return False


def _parse_modules_status(payload: Any) -> list[PortmasterModuleRow]:
    """Flatten the /modules/status JSON into a list of (name, status) rows.

    The exact schema is documented as 'in progress' on the Safing docs, but the
    response is a JSON map from module name to a status object. We surface the
    'status' string and any failure message if present, and ignore anything we
    can't parse — this is best-effort enrichment, not load-bearing.
    """
    rows: list[PortmasterModuleRow] = []
    if not isinstance(payload, dict):
        return rows
    for name, info in payload.items():
        if not isinstance(info, dict):
            continue
        status = info.get("Status") or info.get("status") or "unknown"
        failure = info.get("FailureMsg") or info.get("failure_msg")
        rows.append(PortmasterModuleRow(name=str(name), status=str(status), failure_msg=failure))
    rows.sort(key=lambda r: r.name)
    return rows


def _fetch_modules_status(token: str) -> tuple[dict[str, Any] | None, bool, str | None]:
    """GET /api/v1/modules/status with a bearer token.

    Returns (json, unauthorized, error_message). Unauthorized is True iff the
    server returned 401 — caller should clear the cached token.
    """
    try:
        resp = requests.get(
            f"{PORTMASTER_API_BASE}/modules/status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=PORTMASTER_AUTHED_TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        return None, False, str(e)

    if resp.status_code == 401:
        return None, True, "Token rejected (401)"
    if resp.status_code != 200:
        return None, False, f"HTTP {resp.status_code}"
    try:
        return resp.json(), False, None
    except ValueError as e:
        return None, False, f"Invalid JSON: {e}"


def probe_portmaster(token: str | None = None) -> PortmasterProbeResult:
    """Detect Portmaster and optionally collect module status.

    Returns a PortmasterProbeResult describing what was found. Never raises.
    """
    try:
        if _ping():
            result = PortmasterProbeResult(status=PortmasterStatus.RUNNING)
            if token:
                payload, unauthorized, err = _fetch_modules_status(token)
                if unauthorized:
                    result.modules_unauthorized = True
                    # Caller (system_audit) clears the stale token from the keyring.
                elif payload is not None:
                    result.module_status = payload
                    result.module_rows = _parse_modules_status(payload)
                elif err:
                    logger.debug("modules/status fetch failed: %s", err)
            return result

        if _binary_or_service_present():
            return PortmasterProbeResult(status=PortmasterStatus.INSTALLED_NOT_RUNNING)

        return PortmasterProbeResult(status=PortmasterStatus.NOT_INSTALLED)
    except Exception as e:
        logger.warning("Unexpected error probing Portmaster: %s", e)
        return PortmasterProbeResult(status=PortmasterStatus.ERROR, error=str(e))


def request_app_token(
    app_name: str = "ClamUI",
    read_scope: str = "user",
    write_scope: str = "",
    ttl: str = "24h",
) -> tuple[str | None, str | None]:
    """Initiate Portmaster's third-party authorization flow.

    Calls GET /api/v1/app/auth which prompts the user inside Portmaster to
    approve or deny ClamUI. Returns (token, error). On user denial returns
    (None, None) — that is the expected silent-fail path. On a network error
    returns (None, message).

    Note: this call blocks until the user responds in Portmaster's UI (or it
    times out at PORTMASTER_AUTH_TIMEOUT seconds), so callers must invoke it
    from a worker thread.
    """
    params: dict[str, str] = {"app-name": app_name, "ttl": ttl}
    if read_scope:
        params["read"] = read_scope
    if write_scope:
        params["write"] = write_scope

    try:
        resp = requests.get(
            f"{PORTMASTER_API_BASE}/app/auth",
            params=params,
            timeout=PORTMASTER_AUTH_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return None, "Authorization request timed out"
    except requests.exceptions.RequestException as e:
        return None, str(e)

    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError:
            # Some Portmaster builds return text/plain — fall through to raw text.
            return resp.text.strip() or None, None
        token = data.get("token") or data.get("Token") or data.get("key")
        return (token, None) if token else (None, "No token in response")
    if resp.status_code in (401, 403):
        # User declined — not an error from our perspective.
        return None, None
    return None, f"HTTP {resp.status_code}"
