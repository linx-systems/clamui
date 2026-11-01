use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::net::IpAddr;
use std::time::Duration;

use crate::common::{now_iso, sanitize_line, Context};
use crate::host_probe::{run_limited_command, LimitedCommandOutput};
use crate::AppResult;

mod public_ip;

const SOCKET_TIMEOUT: Duration = Duration::from_secs(3);
const SOCKET_OUTPUT_LIMIT: usize = 2 * 1024 * 1024;
const MAX_SOCKETS: usize = 4096;
const SS_ARGUMENTS: [&str; 7] = [
    "--no-header",
    "--numeric",
    "--all",
    "--tcp",
    "--udp",
    "--processes",
    "--oneline",
];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkSnapshotStatus {
    Available,
    Partial,
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct NetworkEndpoint {
    pub address: String,
    pub port: Option<u16>,
    pub virustotal_url: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct NetworkProcess {
    pub name: String,
    pub pid: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkProtocol {
    Tcp,
    Udp,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkSocketKind {
    Listener,
    Connection,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct NetworkSocket {
    pub protocol: NetworkProtocol,
    pub state: String,
    pub kind: NetworkSocketKind,
    pub local: NetworkEndpoint,
    pub remote: Option<NetworkEndpoint>,
    pub processes: Vec<NetworkProcess>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct NetworkSnapshot {
    pub status: NetworkSnapshotStatus,
    pub captured_at: String,
    pub sockets: Vec<NetworkSocket>,
    pub unparsed_lines: usize,
    pub limited: bool,
    pub message: Option<String>,
}

fn tr(ctx: &Context, message: &str) -> String {
    crate::i18n::translate(ctx, message)
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    if action != "snapshot" {
        let message = tr(ctx, "Network action is not supported.");
        return Err(message);
    }
    if !args.as_object().is_some_and(|object| object.is_empty()) {
        let message = tr(ctx, "Network snapshot accepts no arguments.");
        return Err(message);
    }

    serde_json::to_value(snapshot(ctx)).map_err(|error| error.to_string())
}

fn snapshot(ctx: &Context) -> NetworkSnapshot {
    let output = run_limited_command("ss", &SS_ARGUMENTS, SOCKET_TIMEOUT, SOCKET_OUTPUT_LIMIT);
    snapshot_from_output(ctx, &output)
}

fn snapshot_from_output(ctx: &Context, output: &LimitedCommandOutput) -> NetworkSnapshot {
    let captured_at = now_iso();
    if let Some(message) = unavailable_message(ctx, output) {
        return NetworkSnapshot {
            status: NetworkSnapshotStatus::Unavailable,
            captured_at,
            sockets: Vec::new(),
            unparsed_lines: 0,
            limited: false,
            message: Some(message),
        };
    }

    let parsed = parse_sockets(&output.stdout);
    let message = match (parsed.unparsed_lines > 0, parsed.limited) {
        (true, true) => {
            let message = tr(
                ctx,
                "Some network socket rows could not be read, and the list was limited to 4096 rows.",
            );
            Some(message)
        }
        (true, false) => {
            let message = tr(ctx, "Some network socket rows could not be read.");
            Some(message)
        }
        (false, true) => {
            let message = tr(ctx, "Network socket list was limited to 4096 rows.");
            Some(message)
        }
        (false, false) => None,
    };
    let status = if message.is_some() {
        NetworkSnapshotStatus::Partial
    } else {
        NetworkSnapshotStatus::Available
    };

    NetworkSnapshot {
        status,
        captured_at,
        sockets: parsed.sockets,
        unparsed_lines: parsed.unparsed_lines,
        limited: parsed.limited,
        message,
    }
}

fn unavailable_message(ctx: &Context, output: &LimitedCommandOutput) -> Option<String> {
    if output.timed_out {
        let message = tr(ctx, "Network socket listing timed out. Try again.");
        return Some(message);
    }
    if output.truncated {
        let message = tr(
            ctx,
            "Network socket listing could not be completed safely. Try again.",
        );
        return Some(message);
    }
    if output.invalid_utf8 {
        let message = tr(
            ctx,
            "Network socket listing returned invalid text and could not be read safely.",
        );
        return Some(message);
    }
    if output.code != Some(0) {
        let message = tr(
            ctx,
            "Network socket listing is unavailable. Check that the system socket tool is installed and try again.",
        );
        return Some(message);
    }
    None
}

#[derive(Debug)]
struct ParsedSockets {
    sockets: Vec<NetworkSocket>,
    unparsed_lines: usize,
    limited: bool,
}

fn parse_sockets(output: &str) -> ParsedSockets {
    let mut sockets = Vec::new();
    let mut unparsed_lines = 0;
    let mut limited = false;

    for line in output.lines().filter(|line| !line.trim().is_empty()) {
        let Some(socket) = parse_socket_line(line) else {
            unparsed_lines += 1;
            continue;
        };
        if sockets.len() == MAX_SOCKETS {
            limited = true;
            continue;
        }
        sockets.push(socket);
    }

    ParsedSockets {
        sockets,
        unparsed_lines,
        limited,
    }
}

fn parse_socket_line(line: &str) -> Option<NetworkSocket> {
    let mut remainder = line;
    let netid = next_column(&mut remainder)?;
    let state = next_column(&mut remainder)?;
    next_column(&mut remainder)?;
    next_column(&mut remainder)?;
    let local = parse_endpoint(next_column(&mut remainder)?)?;
    let peer = parse_endpoint(next_column(&mut remainder)?)?;

    let protocol = match netid {
        "tcp" | "tcp6" => NetworkProtocol::Tcp,
        "udp" | "udp6" => NetworkProtocol::Udp,
        _ => return None,
    };
    if !supported_state(protocol, state) {
        return None;
    }

    let remote = (!peer.is_wildcard).then_some(peer.endpoint);
    let kind = match (protocol, state, remote.is_some()) {
        (NetworkProtocol::Tcp, "LISTEN", false) => NetworkSocketKind::Listener,
        (NetworkProtocol::Udp, "UNCONN", false) => NetworkSocketKind::Listener,
        (NetworkProtocol::Tcp, _, true) if state != "LISTEN" => NetworkSocketKind::Connection,
        (NetworkProtocol::Udp, _, true) if state != "UNCONN" => NetworkSocketKind::Connection,
        _ => return None,
    };

    Some(NetworkSocket {
        protocol,
        state: state.to_owned(),
        kind,
        local: local.endpoint,
        remote,
        processes: parse_processes(remainder),
    })
}

fn next_column<'a>(remainder: &mut &'a str) -> Option<&'a str> {
    *remainder = remainder.trim_start_matches(char::is_whitespace);
    let end = remainder
        .find(char::is_whitespace)
        .unwrap_or(remainder.len());
    if end == 0 {
        return None;
    }
    let (column, tail) = remainder.split_at(end);
    *remainder = tail;
    Some(column)
}

fn supported_state(protocol: NetworkProtocol, state: &str) -> bool {
    match protocol {
        NetworkProtocol::Tcp => matches!(
            state,
            "ESTAB"
                | "SYN-SENT"
                | "SYN-RECV"
                | "FIN-WAIT-1"
                | "FIN-WAIT-2"
                | "TIME-WAIT"
                | "CLOSE"
                | "CLOSE-WAIT"
                | "LAST-ACK"
                | "LISTEN"
                | "CLOSING"
                | "NEW-SYN-RECV"
        ),
        NetworkProtocol::Udp => matches!(state, "UNCONN" | "ESTAB" | "CLOSE"),
    }
}

struct EndpointParts<'a> {
    address: &'a str,
    scope: Option<&'a str>,
    port: &'a str,
}

#[derive(Debug)]
struct ParsedEndpoint {
    endpoint: NetworkEndpoint,
    is_wildcard: bool,
}

fn parse_endpoint(value: &str) -> Option<ParsedEndpoint> {
    let parts = split_endpoint(value)?;
    let port = parse_port(parts.port)?;
    if parts.address == "*" && parts.scope.is_none() {
        return Some(ParsedEndpoint {
            endpoint: NetworkEndpoint {
                address: "*".to_owned(),
                port,
                virustotal_url: None,
            },
            is_wildcard: true,
        });
    }

    let (raw_ip, legacy_scope) = match parts.address.split_once('%') {
        Some((ip, scope)) if !scope.is_empty() && !scope.contains('%') => (ip, Some(scope)),
        Some(_) => return None,
        None => (parts.address, None),
    };
    if legacy_scope.is_some() && parts.scope.is_some() {
        return None;
    }
    let scope = parts.scope.or(legacy_scope);
    let ip = raw_ip.parse::<IpAddr>().ok()?;
    if !scope.is_none_or(valid_scope) {
        return None;
    }

    let mut canonical = ip.to_string();
    if let Some(scope) = scope {
        canonical.push('%');
        canonical.push_str(scope);
    }
    let is_wildcard = ip.is_unspecified();
    let virustotal_url = (!is_wildcard && scope.is_none())
        .then(|| public_ip::virustotal_url(ip))
        .flatten();
    Some(ParsedEndpoint {
        endpoint: NetworkEndpoint {
            address: canonical,
            port,
            virustotal_url,
        },
        is_wildcard,
    })
}

fn split_endpoint(value: &str) -> Option<EndpointParts<'_>> {
    if let Some(value) = value.strip_prefix('[') {
        let (address, suffix) = value.split_once(']')?;
        if address.is_empty() {
            return None;
        }
        if let Some(port) = suffix.strip_prefix(':') {
            return Some(EndpointParts {
                address,
                scope: None,
                port,
            });
        }
        let suffix = suffix.strip_prefix('%')?;
        let (scope, port) = suffix.split_once(':')?;
        return Some(EndpointParts {
            address,
            scope: Some(scope),
            port,
        });
    }
    let (address, port) = value.rsplit_once(':')?;
    Some(EndpointParts {
        address,
        scope: None,
        port,
    })
}

fn parse_port(value: &str) -> Option<Option<u16>> {
    if value == "*" {
        return Some(None);
    }
    value.parse::<u16>().ok().map(Some)
}

fn valid_scope(scope: &str) -> bool {
    !scope.is_empty()
        && scope.len() <= 15
        && scope
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-'))
}

fn parse_processes(suffix: &str) -> Vec<NetworkProcess> {
    let suffix = suffix.trim();
    let Some(rest) = suffix.strip_prefix("users:(") else {
        return Vec::new();
    };
    let bytes = rest.as_bytes();
    let mut position = 0;
    let mut processes = Vec::new();

    loop {
        if bytes.get(position) != Some(&b'(') || bytes.get(position + 1) != Some(&b'\"') {
            return Vec::new();
        }
        position += 2;
        let name_start = position;
        let name_end = loop {
            match bytes.get(position) {
                Some(b'\\') => {
                    position += 2;
                    if position > bytes.len() {
                        return Vec::new();
                    }
                }
                Some(b'\"') => break position,
                Some(_) => position += 1,
                None => return Vec::new(),
            }
        };
        let raw_name = &rest[name_start..name_end];
        position += 1;
        if !rest[position..].starts_with(",pid=") {
            return Vec::new();
        }
        position += ",pid=".len();
        let pid_start = position;
        while bytes.get(position).is_some_and(u8::is_ascii_digit) {
            position += 1;
        }
        if pid_start == position {
            return Vec::new();
        }
        let Ok(pid) = rest[pid_start..position].parse::<u32>() else {
            return Vec::new();
        };
        if pid == 0 || pid > i32::MAX as u32 {
            return Vec::new();
        }
        while bytes.get(position) == Some(&b',') {
            position += 1;
            let field_start = position;
            while bytes.get(position).is_some_and(|byte| {
                byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'=' | b'.' | b'-')
            }) {
                position += 1;
            }
            if field_start == position {
                return Vec::new();
            }
        }
        if bytes.get(position) != Some(&b')') {
            return Vec::new();
        }
        position += 1;

        let name = sanitize_line(raw_name).trim().to_owned();
        if name.is_empty() {
            return Vec::new();
        }
        processes.push(NetworkProcess { name, pid });

        match bytes.get(position) {
            Some(b',') => position += 1,
            Some(b')') if position + 1 == bytes.len() => return processes,
            _ => return Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(line: &str) -> NetworkSocket {
        parse_socket_line(line).expect("valid socket row")
    }

    #[test]
    fn parses_numeric_ipv4_ipv6_scopes_wildcards_and_port_boundaries() {
        let ipv4 = parse("tcp LISTEN 0 128 0.0.0.0:0 0.0.0.0:*");
        assert_eq!(ipv4.local.address, "0.0.0.0");
        assert_eq!(ipv4.local.port, Some(0));
        assert!(ipv4.remote.is_none());

        let ipv6 = parse("tcp ESTAB 0 0 [2001:4860::1]:65535 [2606:4700::1]:443");
        assert_eq!(ipv6.local.address, "2001:4860::1");
        assert_eq!(ipv6.local.port, Some(65535));
        assert_eq!(ipv6.remote.as_ref().unwrap().address, "2606:4700::1");

        let scoped = parse("udp UNCONN 0 0 [2001:4860::1%eth0]:53 [::]:*");
        assert_eq!(scoped.local.address, "2001:4860::1%eth0");
        assert!(scoped.local.virustotal_url.is_none());
        assert!(scoped.remote.is_none());

        let device_bound = parse(
            "udp ESTAB 0 0 192.0.2.35%enp191s0:68 198.51.100.1%wan0:67 users:((\"dhcp\",pid=42,fd=3))",
        );
        assert_eq!(device_bound.state, "ESTAB");
        assert_eq!(device_bound.local.address, "192.0.2.35%enp191s0");
        assert_eq!(device_bound.local.port, Some(68));
        assert!(device_bound.local.virustotal_url.is_none());
        let peer = device_bound.remote.as_ref().expect("peer endpoint");
        assert_eq!(peer.address, "198.51.100.1%wan0");
        assert_eq!(peer.port, Some(67));
        assert!(peer.virustotal_url.is_none());
        assert_eq!(
            device_bound.processes,
            vec![NetworkProcess {
                name: "dhcp".to_owned(),
                pid: 42
            }]
        );

        let native_listener = parse("udp UNCONN 0 0 [fe80::1]%eth0:546 [::]:*");
        assert_eq!(native_listener.state, "UNCONN");
        assert_eq!(native_listener.local.address, "fe80::1%eth0");
        assert_eq!(native_listener.local.port, Some(546));
        assert!(native_listener.local.virustotal_url.is_none());
        assert!(native_listener.remote.is_none());

        let scoped_peer = parse("tcp ESTAB 0 0 [fe80::1]%eth0:80 [fe80::2]%eth1:443");
        assert_eq!(scoped_peer.state, "ESTAB");
        assert_eq!(scoped_peer.local.address, "fe80::1%eth0");
        assert_eq!(scoped_peer.local.port, Some(80));
        assert!(scoped_peer.local.virustotal_url.is_none());
        let peer = scoped_peer.remote.as_ref().expect("peer endpoint");
        assert_eq!(peer.address, "fe80::2%eth1");
        assert_eq!(peer.port, Some(443));
        assert!(peer.virustotal_url.is_none());

        let wildcard = parse("udp UNCONN 0 0 *:* *:*");
        assert_eq!(wildcard.local.address, "*");
        assert_eq!(wildcard.local.port, None);
        assert!(wildcard.remote.is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 [::1%bad/scope]:80 [::]:*").is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 [::1]%bad/scope:80 [::]:*").is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 [::1]%eth0%extra:80 [::]:*").is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 [::1%eth0]%wan0:80 [::]:*").is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 [::1]eth0:80 [::]:*").is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 192.0.2.35%:80 0.0.0.0:*").is_none());
        assert!(parse_socket_line("tcp LISTEN 0 0 192.0.2.35%bad%scope:80 0.0.0.0:*").is_none());
        assert!(
            parse_socket_line("tcp LISTEN 0 0 192.0.2.35%scope-name-too-long:80 0.0.0.0:*")
                .is_none()
        );
        assert!(parse_socket_line("tcp LISTEN 0 0 127.0.0.1:65536 0.0.0.0:*").is_none());
    }

    #[test]
    fn distinguishes_tcp_udp_bound_sockets_from_connections_without_direction_claims() {
        let tcp_listener = parse("tcp LISTEN 0 4096 127.0.0.1:8080 0.0.0.0:*");
        assert_eq!(tcp_listener.kind, NetworkSocketKind::Listener);
        assert!(tcp_listener.remote.is_none());

        let tcp_connection = parse("tcp ESTAB 0 0 127.0.0.1:8080 192.0.2.1:55432");
        assert_eq!(tcp_connection.kind, NetworkSocketKind::Connection);
        assert_eq!(tcp_connection.remote.as_ref().unwrap().port, Some(55432));

        let udp_bound = parse("udp UNCONN 0 0 127.0.0.1:5353 0.0.0.0:*");
        assert_eq!(udp_bound.kind, NetworkSocketKind::Listener);
        let udp_connection = parse("udp ESTAB 0 0 192.0.2.2:5353 192.0.2.3:5354");
        assert_eq!(udp_connection.kind, NetworkSocketKind::Connection);
        assert!(parse_socket_line("tcp ESTAB 0 0 127.0.0.1:1 0.0.0.0:*").is_none());
    }

    #[test]
    fn preserves_only_complete_unambiguous_process_owners() {
        let missing = parse("tcp LISTEN 0 128 127.0.0.1:80 0.0.0.0:*");
        assert!(missing.processes.is_empty());

        let multiple = parse("tcp LISTEN 0 128 127.0.0.1:80 0.0.0.0:* users:((\"worker one\",pid=41,fd=3),(\"worker two\",pid=42,fd=4))");
        assert_eq!(multiple.processes.len(), 2);
        assert_eq!(multiple.processes[0].name, "worker one");
        assert_eq!(multiple.processes[1].pid, 42);

        let malformed =
            parse("tcp LISTEN 0 128 127.0.0.1:80 0.0.0.0:* users:((\"name pid=999\",fd=3))");
        assert!(malformed.processes.is_empty());
        let ambiguous =
            parse("tcp LISTEN 0 128 127.0.0.1:80 0.0.0.0:* users:((\"name\",pid=0,fd=3))");
        assert!(ambiguous.processes.is_empty());
    }

    #[test]
    fn classifies_empty_malformed_and_capped_data_for_snapshot_consumers() {
        let ctx = test_context();
        let empty = snapshot_from_output(&ctx, &output(Some(0), false, false, false));
        assert_eq!(empty.status, NetworkSnapshotStatus::Available);
        assert!(empty.sockets.is_empty());
        assert_eq!(empty.unparsed_lines, 0);
        assert!(empty.message.is_none());

        let malformed = snapshot_from_output(
            &ctx,
            &LimitedCommandOutput {
                code: Some(0),
                stdout: "not an ss row\n".to_owned(),
                timed_out: false,
                truncated: false,
                invalid_utf8: false,
            },
        );
        assert_eq!(malformed.status, NetworkSnapshotStatus::Partial);
        assert!(malformed.sockets.is_empty());
        assert_eq!(malformed.unparsed_lines, 1);
        assert!(malformed.message.is_some());

        let capped_input = "tcp LISTEN 0 1 127.0.0.1:80 0.0.0.0:*\n".repeat(MAX_SOCKETS + 1);
        let capped = snapshot_from_output(
            &ctx,
            &LimitedCommandOutput {
                code: Some(0),
                stdout: capped_input,
                timed_out: false,
                truncated: false,
                invalid_utf8: false,
            },
        );
        assert_eq!(capped.status, NetworkSnapshotStatus::Partial);
        assert_eq!(capped.sockets.len(), MAX_SOCKETS);
        assert!(capped.limited);
    }

    #[test]
    fn reports_success_and_failed_probe_results_to_snapshot_consumers() {
        let ctx = test_context();
        assert_eq!(
            snapshot_from_output(&ctx, &output(Some(0), false, false, false)).status,
            NetworkSnapshotStatus::Available
        );
        for failed in [
            output(Some(1), false, false, false),
            output(Some(0), true, false, false),
            output(Some(0), false, true, false),
            output(Some(0), false, false, true),
        ] {
            let snapshot = snapshot_from_output(&ctx, &failed);
            assert_eq!(snapshot.status, NetworkSnapshotStatus::Unavailable);
            assert!(snapshot.sockets.is_empty());
            assert!(snapshot.message.is_some());
        }
    }

    #[test]
    fn snapshot_wire_rejects_unknown_actions_and_nonempty_arguments() {
        let ctx = test_context();
        assert!(dispatch(&ctx, "other", serde_json::json!({})).is_err());
        assert!(dispatch(&ctx, "snapshot", serde_json::Value::Null).is_err());
        assert!(dispatch(&ctx, "snapshot", serde_json::json!({"ignored": true})).is_err());
    }

    fn test_context() -> Context {
        Context::with_paths(crate::common::Paths {
            home: "/tmp/clamui-network-test-home".into(),
            config_dir: "/tmp/clamui-network-test-config".into(),
            data_dir: "/tmp/clamui-network-test-data".into(),
        })
        .expect("test context")
    }

    fn output(
        code: Option<i32>,
        timed_out: bool,
        truncated: bool,
        invalid_utf8: bool,
    ) -> LimitedCommandOutput {
        LimitedCommandOutput {
            code,
            stdout: String::new(),
            timed_out,
            truncated,
            invalid_utf8,
        }
    }
}
