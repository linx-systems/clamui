use serde::{Deserialize, Serialize};
use std::process::Command;
use std::time::Duration;

use crate::common::{host_command, sanitize_line};
use crate::AppResult;

pub const API_BASE: &str = "http://127.0.0.1:817/api/v1";
pub const PROBE_TIMEOUT: Duration = Duration::from_millis(1_500);
pub const AUTHED_TIMEOUT: Duration = Duration::from_secs(5);
pub const AUTH_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PortmasterStatus {
    Running,
    InstalledNotRunning,
    NotInstalled,
    Error,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PortmasterModuleRow {
    pub name: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub failure_msg: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PortmasterProbeResult {
    pub status: PortmasterStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub modules_unauthorized: bool,
    pub module_rows: Vec<PortmasterModuleRow>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AuthorizationResult {
    pub token: Option<String>,
    pub cancelled: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

fn client(timeout: Duration) -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        // Portmaster is a literal loopback service.  Proxy environment values must
        // never redirect either liveness or authorization requests.
        .no_proxy()
        .timeout(timeout)
        .build()
        .map_err(|error| sanitize_line(&error.to_string()))
}

pub fn ping() -> bool {
    let Ok(client) = client(PROBE_TIMEOUT) else {
        return false;
    };
    match client.get(format!("{API_BASE}/ping")).send() {
        Ok(response) => {
            response.status().as_u16() == 200
                && response
                    .text()
                    .map(|body| body.contains("Pong"))
                    .unwrap_or(false)
        }
        Err(_) => false,
    }
}

fn command_succeeds(program: &str, args: &[&str]) -> bool {
    let arguments = args
        .iter()
        .map(|value| (*value).to_owned())
        .collect::<Vec<_>>();
    let mut command: Command = host_command(program, &arguments);
    command
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

/// `systemctl is-active` cannot distinguish an absent unit from a stopped one.
/// Check both installation indicators after the loopback ping has failed.
pub fn binary_or_service_present() -> bool {
    command_succeeds("which", &["portmaster-start"])
        || command_succeeds("systemctl", &["cat", "portmaster.service"])
}

pub fn parse_modules_status(payload: &serde_json::Value) -> Vec<PortmasterModuleRow> {
    let Some(modules) = payload.as_object() else {
        return Vec::new();
    };
    let mut rows = modules
        .iter()
        .filter_map(|(name, value)| {
            let info = value.as_object()?;
            let status = info
                .get("Status")
                .or_else(|| info.get("status"))
                .and_then(serde_json::Value::as_str)
                .unwrap_or("unknown");
            let failure_msg = info
                .get("FailureMsg")
                .or_else(|| info.get("failure_msg"))
                .and_then(serde_json::Value::as_str)
                .map(sanitize_line)
                .filter(|message| !message.is_empty());
            Some(PortmasterModuleRow {
                name: sanitize_line(name),
                status: sanitize_line(status),
                failure_msg,
            })
        })
        .collect::<Vec<_>>();
    rows.sort_by(|left, right| left.name.cmp(&right.name));
    rows
}

fn fetch_modules_status(token: &str) -> Result<Result<Vec<PortmasterModuleRow>, ()>, String> {
    let client = client(AUTHED_TIMEOUT)?;
    let response = client
        .get(format!("{API_BASE}/modules/status"))
        .bearer_auth(token)
        .send()
        .map_err(|error| sanitize_line(&error.to_string()))?;
    if response.status().as_u16() == 401 {
        return Ok(Err(()));
    }
    if response.status().as_u16() != 200 {
        return Err(format!("HTTP {}", response.status().as_u16()));
    }
    let payload = response
        .json::<serde_json::Value>()
        .map_err(|error| format!("Invalid JSON: {}", sanitize_line(&error.to_string())))?;
    Ok(Ok(parse_modules_status(&payload)))
}

/// Probe the optional service.  An unavailable loopback endpoint is not an
/// error: only a confirmed installation changes it to `InstalledNotRunning`.
pub fn probe(token: Option<&str>) -> PortmasterProbeResult {
    if !ping() {
        return PortmasterProbeResult {
            status: if binary_or_service_present() {
                PortmasterStatus::InstalledNotRunning
            } else {
                PortmasterStatus::NotInstalled
            },
            error: None,
            modules_unauthorized: false,
            module_rows: Vec::new(),
        };
    }

    let mut result = PortmasterProbeResult {
        status: PortmasterStatus::Running,
        error: None,
        modules_unauthorized: false,
        module_rows: Vec::new(),
    };
    if let Some(token) = token.filter(|token| !token.is_empty()) {
        match fetch_modules_status(token) {
            Ok(Ok(rows)) => result.module_rows = rows,
            Ok(Err(())) => result.modules_unauthorized = true,
            // Module status is optional enrichment. The working service remains
            // RUNNING even if this separately privileged endpoint is unavailable.
            Err(_) => {}
        }
    }
    result
}

/// Start the *user-authorized* Portmaster application authorization flow.  No
/// arbitrary caller-provided scopes, endpoint, or application identity are
/// accepted; user denial is an expected cancelled outcome.
pub fn request_app_token() -> AuthorizationResult {
    let client = match client(AUTH_TIMEOUT) {
        Ok(client) => client,
        Err(error) => {
            return AuthorizationResult {
                token: None,
                cancelled: false,
                error: Some(error),
            }
        }
    };
    let response = match client
        .get(format!("{API_BASE}/app/auth"))
        .query(&[("app-name", "ClamUI"), ("ttl", "24h"), ("read", "user")])
        .send()
    {
        Ok(response) => response,
        Err(error) => {
            return AuthorizationResult {
                token: None,
                cancelled: false,
                error: Some(sanitize_line(&error.to_string())),
            }
        }
    };
    if matches!(response.status().as_u16(), 401 | 403) {
        return AuthorizationResult {
            token: None,
            cancelled: true,
            error: None,
        };
    }
    if response.status().as_u16() != 200 {
        return AuthorizationResult {
            token: None,
            cancelled: false,
            error: Some(format!("HTTP {}", response.status().as_u16())),
        };
    }
    let body = match response.text() {
        Ok(body) => body,
        Err(error) => {
            return AuthorizationResult {
                token: None,
                cancelled: false,
                error: Some(sanitize_line(&error.to_string())),
            }
        }
    };
    let token = parse_authorization_response(&body);
    AuthorizationResult {
        error: token.is_none().then(|| "No token in response".to_owned()),
        token,
        cancelled: false,
    }
}

/// Parse a successful authorization response without accepting unrelated JSON
/// as an opaque token. Plain text remains compatible with older Portmaster
/// releases that do not set an application/json content type.
pub fn parse_authorization_response(body: &str) -> Option<String> {
    match serde_json::from_str::<serde_json::Value>(body) {
        Ok(value) => value
            .get("token")
            .or_else(|| value.get("Token"))
            .or_else(|| value.get("key"))
            .and_then(serde_json::Value::as_str)
            .map(str::trim)
            .filter(|token| !token.is_empty())
            .map(str::to_owned),
        Err(_) => {
            let token = body.trim();
            (!token.is_empty()).then(|| token.to_owned())
        }
    }
}

pub fn launch(command: &str) -> AppResult<bool> {
    // This is intentionally a strict allowlist, not a generic process endpoint.
    if !matches!(command, "gufw" | "firewall-config") {
        return Err("Unsupported audit launch action".to_owned());
    }
    let mut process = host_command(command, &[]);
    process
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map(|_| true)
        .map_err(|error| sanitize_line(&error.to_string()))
}
