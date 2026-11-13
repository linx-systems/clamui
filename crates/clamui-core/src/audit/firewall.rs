use super::{
    tr, AuditCategory, AuditCheck, AuditSection, AuditStatus, Context, URL_FIREWALLD, URL_NFTABLES,
    URL_UFW,
};
use crate::host_probe::{run_limited_command, LimitedCommandOutput};
use serde_json::Value;
use std::collections::{BTreeMap, VecDeque};
use std::path::{Path, PathBuf};
use std::time::Duration;

const PROBE_TIMEOUT: Duration = Duration::from_secs(2);
const AUTH_TIMEOUT: Duration = Duration::from_secs(120);
const PROBE_OUTPUT_LIMIT: usize = 256 * 1024;
const UFW_PATHS: [&str; 3] = ["/usr/sbin/ufw", "/usr/bin/ufw", "/sbin/ufw"];

pub(super) fn check_firewall(ctx: &Context) -> AuditSection {
    let ufw = inspect_ufw(&probe("ufw", &["status", "verbose"]));
    build_firewall(ctx, ufw)
}

fn build_firewall(ctx: &Context, ufw: UfwState) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::Firewall,
        "Firewall",
        "security-medium-symbolic",
    );

    add_ufw(ctx, &mut section, ufw, || trusted_ufw_path().is_some());

    let firewalld = inspect_firewalld_owner(&probe(
        "busctl",
        &[
            "--system",
            "--auto-start=no",
            "--allow-interactive-authorization=no",
            "--timeout=2",
            "--json=short",
            "call",
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            "s",
            "org.fedoraproject.FirewallD1",
        ],
    ));
    add_firewalld(ctx, &mut section, firewalld);
    add_firewalld_command(ctx, &mut section, command_available("firewall-cmd"));

    let nft = probe("nft", &["--json", "list", "ruleset"]);
    add_nftables(ctx, &mut section, inspect_nft(&nft));

    let iptables4 = probe("iptables-save", &[]);
    add_iptables4(ctx, &mut section, inspect_iptables(&iptables4));
    let iptables6 = probe("ip6tables-save", &[]);
    add_iptables6(ctx, &mut section, inspect_iptables(&iptables6));

    if manager_overlap(ufw, firewalld) {
        let name = tr(ctx, "Firewall manager overlap");
        section.push(AuditCheck::new(name, AuditStatus::Warning, tr(
            ctx,
            "UFW is active while Firewalld owns its D-Bus name; their rule interaction was not evaluated.",
        )));
    }

    super::check_open_ports(ctx, &mut section);
    add_gufw(ctx, &mut section, command_available("gufw"));
    add_firewall_config(ctx, &mut section, command_available("firewall-config"));
    add_plasma_firewall(ctx, &mut section, plasma_firewall_installed());
    section
}

fn probe(program: &str, args: &[&str]) -> LimitedCommandOutput {
    run_limited_command(program, args, PROBE_TIMEOUT, PROBE_OUTPUT_LIMIT)
}

fn trusted_ufw_path() -> Option<&'static str> {
    UFW_PATHS
        .into_iter()
        .find(|path| trusted_host_executable(path))
}

fn trusted_host_executable(path: &str) -> bool {
    trusted_path_with(
        path,
        |path| {
            let path = path.to_str()?;
            let output = probe("/usr/bin/stat", &["--format=%u:%f", "--", path]);
            if !usable(&output) {
                return None;
            }
            let (uid, mode) = output.stdout.trim().split_once(':')?;
            Some((
                uid.parse::<u32>().ok()?,
                u32::from_str_radix(mode, 16).ok()?,
            ))
        },
        |path| {
            let path = path.to_str()?;
            let output = probe("/usr/bin/readlink", &["--", path]);
            if !usable(&output) {
                return None;
            }
            Some(output.stdout.strip_suffix('\n')?.to_owned())
        },
    )
}

fn trusted_path_with(
    path: &str,
    metadata: impl Fn(&Path) -> Option<(u32, u32)>,
    read_link: impl Fn(&Path) -> Option<String>,
) -> bool {
    fn components(path: &str) -> Option<VecDeque<String>> {
        Path::new(path)
            .components()
            .map(|part| part.as_os_str().to_str().map(str::to_owned))
            .collect()
    }
    let Some(mut pending) = components(path) else {
        return false;
    };
    let Some((0, root_mode)) = metadata(Path::new("/")) else {
        return false;
    };
    if root_mode & 0o170000 != 0o040000 || root_mode & 0o022 != 0 {
        return false;
    }
    let mut current = PathBuf::from("/");
    // Bound both symlink cycles and hostile host path lengths.
    for _ in 0..40 {
        let Some(part) = pending.pop_front() else {
            return false;
        };
        match part.as_str() {
            "/" => {
                current = PathBuf::from("/");
                continue;
            }
            "." => continue,
            ".." => {
                current.pop();
                continue;
            }
            _ => current.push(part),
        }
        let Some((0, mode)) = metadata(&current) else {
            return false;
        };
        match mode & 0o170000 {
            0o120000 => {
                let Some(target) = read_link(&current) else {
                    return false;
                };
                let Some(mut target_parts) = components(&target) else {
                    return false;
                };
                if target_parts.is_empty() {
                    return false;
                }
                current.pop();
                target_parts.append(&mut pending);
                pending = target_parts;
            }
            0o040000 if !pending.is_empty() && mode & 0o022 == 0 => {}
            0o100000 if pending.is_empty() && mode & 0o022 == 0 && mode & 0o100 != 0 => {
                return true;
            }
            _ => return false,
        }
    }
    false
}

pub(super) fn request_ufw_status(ctx: &Context) -> crate::AppResult<Value> {
    let Some(path) = trusted_ufw_path() else {
        // Translators: UFW is the name of the firewall application.
        return Err(tr(ctx, "UFW was not found at a trusted system path."));
    };
    if !trusted_host_executable("/usr/bin/pkexec") {
        return Err(tr(
            ctx,
            // Translators: UFW is the name of the firewall application.
            "Administrator authorization for the UFW status check was denied or unavailable.",
        ));
    }
    let output = run_limited_command(
        "/usr/bin/pkexec",
        &["--disable-internal-agent", path, "status", "verbose"],
        AUTH_TIMEOUT,
        PROBE_OUTPUT_LIMIT,
    );
    finish_ufw_status(ctx, &output, |state| build_firewall(ctx, state))
}

fn finish_ufw_status(
    ctx: &Context,
    output: &LimitedCommandOutput,
    build: impl FnOnce(UfwState) -> AuditSection,
) -> crate::AppResult<Value> {
    if output.timed_out {
        // Translators: UFW is the name of the firewall application.
        return Err(tr(ctx, "The UFW status check timed out."));
    }
    if output.truncated || output.invalid_utf8 || output.code.is_none() {
        return Err(tr(
            ctx,
            // Translators: UFW is the name of the firewall application.
            "The UFW status check returned incomplete or invalid output.",
        ));
    }
    match output.code {
        Some(126) => return Ok(serde_json::json!({"cancelled": true})),
        Some(127) => {
            return Err(tr(
                ctx,
                // Translators: UFW is the name of the firewall application.
                "Administrator authorization for the UFW status check was denied or unavailable.",
            ));
        }
        Some(0) => {}
        _ => {
            // Translators: UFW is the name of the firewall application.
            return Err(tr(ctx, "The UFW status check failed."));
        }
    }
    let state = inspect_ufw(output);
    if matches!(
        state,
        UfwState::Unknown
            | UfwState::Active {
                incoming: InputPolicy::Unverified,
                ..
            }
    ) {
        return Err(tr(
            ctx,
            // Translators: UFW is the name of the firewall application.
            "The UFW status check returned incomplete or invalid output.",
        ));
    }
    let section = build(state);
    ctx.emit(
        "audit-progress",
        serde_json::json!({"section": section, "index": 0, "total": 1}),
    );
    Ok(serde_json::json!({"cancelled": false, "section": section}))
}

fn usable(output: &LimitedCommandOutput) -> bool {
    probe_is_usable(
        output.code,
        output.timed_out,
        output.truncated,
        output.invalid_utf8,
    )
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum InputPolicy {
    Deny,
    Reject,
    Allow,
    Unverified,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum UfwState {
    Active {
        incoming: InputPolicy,
        listed_exceptions: bool,
    },
    Inactive,
    Unknown,
}

fn inspect_ufw(output: &LimitedCommandOutput) -> UfwState {
    if !usable(output)
        || output
            .stdout
            .chars()
            .any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t'))
    {
        return UfwState::Unknown;
    }
    parse_ufw_status(&output.stdout)
}

fn parse_ufw_status(text: &str) -> UfwState {
    let mut active = None;
    for line in text.lines() {
        let status = match line {
            "Status: active" => true,
            "Status: inactive" => false,
            _ => continue,
        };
        if active.replace(status).is_some() {
            return UfwState::Unknown;
        }
    }
    let Some(active) = active else {
        return UfwState::Unknown;
    };
    if !active {
        return UfwState::Inactive;
    }
    let mut defaults = text
        .lines()
        .filter_map(|line| line.strip_prefix("Default: "));
    let incoming = match (defaults.next(), defaults.next()) {
        (Some(line), None) => {
            let mut policies = line
                .split(',')
                .filter_map(|part| part.trim().strip_suffix(" (incoming)"));
            match (policies.next(), policies.next()) {
                (Some("deny"), None) => InputPolicy::Deny,
                (Some("reject"), None) => InputPolicy::Reject,
                (Some("allow"), None) => InputPolicy::Allow,
                _ => InputPolicy::Unverified,
            }
        }
        _ => InputPolicy::Unverified,
    };
    let listed_exceptions = text.lines().any(|line| {
        let mut action_seen = false;
        for field in line.split_whitespace() {
            if matches!(field, "ALLOW" | "DENY" | "REJECT") {
                action_seen = true;
            } else if action_seen && field == "IN" {
                return true;
            }
        }
        false
    });
    UfwState::Active {
        incoming,
        listed_exceptions,
    }
}

fn add_ufw(
    ctx: &Context,
    section: &mut AuditSection,
    state: UfwState,
    trusted_available: impl FnOnce() -> bool,
) {
    let name = tr(ctx, "UFW Firewall");
    let mut row = match state {
        UfwState::Active {
            incoming: InputPolicy::Deny,
            listed_exceptions: true,
        } => AuditCheck::new(name, AuditStatus::Pass, tr(
            ctx,
            "UFW is active; the default incoming policy is deny. Listed rules may allow exceptions.",
        )),
        UfwState::Active {
            incoming: InputPolicy::Reject,
            listed_exceptions: true,
        } => AuditCheck::new(name, AuditStatus::Pass, tr(
            ctx,
            "UFW is active; the default incoming policy is reject. Listed rules may allow exceptions.",
        )),
        UfwState::Active {
            incoming: InputPolicy::Deny,
            listed_exceptions: false,
        } => AuditCheck::new(name, AuditStatus::Pass, tr(ctx, "UFW is active; the default incoming policy is deny.")),
        UfwState::Active {
            incoming: InputPolicy::Reject,
            listed_exceptions: false,
        } => AuditCheck::new(name, AuditStatus::Pass, tr(ctx, "UFW is active; the default incoming policy is reject.")),
        UfwState::Active {
            incoming: InputPolicy::Allow,
            ..
        } => AuditCheck::new(name, AuditStatus::Warning, tr(
            ctx,
            "UFW is active, but the default incoming policy allows traffic.",
        )),
        UfwState::Active {
            incoming: InputPolicy::Unverified,
            ..
        } => AuditCheck::new(name, AuditStatus::Unknown, tr(
            ctx,
            "UFW is active, but its default incoming policy could not be verified.",
        )),
        UfwState::Inactive => AuditCheck::new(name, AuditStatus::Warning, tr(ctx, "UFW reports inactive.")),
        UfwState::Unknown => AuditCheck::new(name, AuditStatus::Unknown, tr(ctx, "UFW status could not be inspected safely.")),
    };
    if state == UfwState::Unknown && trusted_available() {
        row.launch_command = Some("__ufw_status__".to_owned());
        // Translators: UFW is the name of the firewall application.
        row.launch_label = Some(tr(ctx, "Check UFW with administrator access"));
        // Translators: UFW is the name of the firewall application.
        row.recommendation = Some(tr(ctx, "Administrator access may be required to read UFW status. This check does not change firewall settings."));
    }
    row.info_url = Some(URL_UFW.to_owned());
    section.push(row);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FirewalldOwner {
    Present,
    Absent,
    Unknown,
}

fn inspect_firewalld_owner(output: &LimitedCommandOutput) -> FirewalldOwner {
    if !usable(output) {
        return FirewalldOwner::Unknown;
    }
    parse_firewalld_owner(&output.stdout)
}

fn parse_firewalld_owner(text: &str) -> FirewalldOwner {
    let Ok(value) = serde_json::from_str::<Value>(text) else {
        return FirewalldOwner::Unknown;
    };
    let Some(data) = value.get("data").and_then(Value::as_array) else {
        return FirewalldOwner::Unknown;
    };
    if value.get("type").and_then(Value::as_str) != Some("b") || data.len() != 1 {
        return FirewalldOwner::Unknown;
    }
    match data.first().and_then(Value::as_bool) {
        Some(true) => FirewalldOwner::Present,
        Some(false) => FirewalldOwner::Absent,
        None => FirewalldOwner::Unknown,
    }
}

fn add_firewalld(ctx: &Context, section: &mut AuditSection, owner: FirewalldOwner) {
    let name = tr(ctx, "Firewalld");
    let mut row = match owner {
        FirewalldOwner::Present => AuditCheck::new(name, AuditStatus::Unknown, tr(
            ctx,
            "Firewalld owns its D-Bus name; readiness and firewall policy were not queried.",
        )),
        FirewalldOwner::Absent => AuditCheck::new(name, AuditStatus::Unknown, tr(
            ctx,
            "No Firewalld D-Bus owner was observed; this does not establish kernel firewall policy.",
        )),
        FirewalldOwner::Unknown => AuditCheck::new(name, AuditStatus::Unknown, tr(
            ctx,
            "Firewalld ownership could not be verified; readiness and firewall policy were not queried.",
        )),
    };
    row.info_url = Some(URL_FIREWALLD.to_owned());
    section.push(row);
}

fn command_available(program: &str) -> bool {
    let output = probe("which", &[program]);
    usable(&output) && !output.stdout.trim().is_empty()
}

fn add_firewalld_command(ctx: &Context, section: &mut AuditSection, present: bool) {
    let name = tr(ctx, "firewall-cmd");
    let row = if present {
        AuditCheck::new(
            name,
            AuditStatus::Pass,
            tr(ctx, "firewall-cmd is installed; it was not executed."),
        )
    } else {
        AuditCheck::new(
            name,
            AuditStatus::Unknown,
            tr(
                ctx,
                "firewall-cmd could not be confirmed without executing it.",
            ),
        )
    };
    section.push(row);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FamilyEvidence {
    Restrictive,
    Permissive,
    Absent,
    Incomplete,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct NativeAssessment {
    ipv4: FamilyEvidence,
    ipv6: FamilyEvidence,
}

fn inspect_nft(output: &LimitedCommandOutput) -> Option<NativeAssessment> {
    usable(output)
        .then(|| parse_nft_ruleset(&output.stdout))
        .flatten()
}

fn parse_nft_ruleset(text: &str) -> Option<NativeAssessment> {
    let value = serde_json::from_str::<Value>(text).ok()?;
    let records = value.get("nftables")?.as_array()?;
    let mut tables = BTreeMap::new();
    for record in records {
        let record = record.as_object()?;
        let Some(table) = record.get("table") else {
            continue;
        };
        let table = table.as_object()?;
        let family = table
            .get("family")?
            .as_str()
            .filter(|value| !value.is_empty())?;
        let name = table
            .get("name")?
            .as_str()
            .filter(|value| !value.is_empty())?;
        let dormant = dormant_flag(table)?;
        if tables.insert((family, name), dormant).is_some() {
            return None;
        }
    }

    let mut ipv4 = Vec::new();
    let mut ipv6 = Vec::new();
    for record in records {
        let record = record.as_object()?;
        let Some(chain) = record.get("chain") else {
            continue;
        };
        let chain = chain.as_object()?;
        if chain.get("hook").and_then(Value::as_str) != Some("input") {
            continue;
        }
        let family = chain
            .get("family")?
            .as_str()
            .filter(|value| !value.is_empty())?;
        if !matches!(family, "ip" | "ip6" | "inet") {
            continue;
        }
        let table = chain
            .get("table")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty());
        let evidence = match table.and_then(|table| tables.get(&(family, table))) {
            Some(true) => continue,
            Some(false) if dormant_flag(chain)? => continue,
            Some(false)
                if chain
                    .get("name")
                    .and_then(Value::as_str)
                    .is_some_and(|name| !name.is_empty())
                    && chain.get("type").and_then(Value::as_str) == Some("filter")
                    && chain.get("prio").is_some_and(|priority| {
                        priority.as_i64().is_some() || priority.as_u64().is_some()
                    }) =>
            {
                match chain.get("policy").and_then(Value::as_str) {
                    Some("drop") => FamilyEvidence::Restrictive,
                    Some("accept") => FamilyEvidence::Permissive,
                    _ => FamilyEvidence::Incomplete,
                }
            }
            _ => FamilyEvidence::Incomplete,
        };
        match family {
            "ip" => ipv4.push(evidence),
            "ip6" => ipv6.push(evidence),
            "inet" => {
                ipv4.push(evidence);
                ipv6.push(evidence);
            }
            _ => unreachable!("relevant nft families are filtered above"),
        }
    }
    Some(NativeAssessment {
        ipv4: combine_family_evidence(&ipv4),
        ipv6: combine_family_evidence(&ipv6),
    })
}

fn dormant_flag(value: &serde_json::Map<String, Value>) -> Option<bool> {
    let Some(flags) = value.get("flags") else {
        return Some(false);
    };
    let flags = flags.as_array()?;
    let mut dormant = false;
    for flag in flags {
        dormant |= flag.as_str()? == "dormant";
    }
    Some(dormant)
}

fn combine_family_evidence(policies: &[FamilyEvidence]) -> FamilyEvidence {
    let Some(first) = policies.first().copied() else {
        return FamilyEvidence::Absent;
    };
    if policies.contains(&FamilyEvidence::Incomplete)
        || policies.iter().any(|policy| *policy != first)
    {
        FamilyEvidence::Incomplete
    } else {
        first
    }
}

fn add_nftables(ctx: &Context, section: &mut AuditSection, assessment: Option<NativeAssessment>) {
    let name = tr(ctx, "nftables (native rules)");
    let mut row = match assessment.map(nft_status) {
        Some(AuditStatus::Pass) => AuditCheck::new(name, AuditStatus::Pass, tr(
            ctx,
            "nftables has restrictive default input policies for IPv4 and IPv6; individual rules may allow exceptions.",
        )),
        Some(AuditStatus::Warning) => AuditCheck::new(name, AuditStatus::Warning, tr(
            ctx,
            "nftables reports a permissive default input policy; remaining coverage may be incomplete",
        )),
        _ => AuditCheck::new(name, AuditStatus::Unknown, tr(
            ctx,
            "nftables input policy coverage could not be verified for both IPv4 and IPv6",
        )),
    };
    row.info_url = Some(URL_NFTABLES.to_owned());
    section.push(row);
}

fn inspect_iptables(output: &LimitedCommandOutput) -> Option<FamilyEvidence> {
    usable(output)
        .then(|| parse_iptables_save(&output.stdout))
        .flatten()
}

fn parse_iptables_save(text: &str) -> Option<FamilyEvidence> {
    let mut in_filter = false;
    let mut filter_seen = false;
    let mut filter_complete = false;
    let mut input_policy = None;
    for line in text.lines() {
        if line == "*filter" {
            if filter_seen || in_filter {
                return None;
            }
            filter_seen = true;
            in_filter = true;
            continue;
        }
        if !in_filter {
            continue;
        }
        if line == "COMMIT" {
            filter_complete = true;
            in_filter = false;
            continue;
        }
        if line.starts_with('*') {
            return None;
        }
        if !line.starts_with(":INPUT") {
            continue;
        }
        if input_policy.is_some() {
            return None;
        }
        let fields = line.split_whitespace().collect::<Vec<_>>();
        input_policy = match fields.as_slice() {
            [":INPUT", "DROP", _] => Some(FamilyEvidence::Restrictive),
            [":INPUT", "ACCEPT", _] => Some(FamilyEvidence::Permissive),
            _ => return None,
        };
    }
    if !filter_seen || !filter_complete {
        return None;
    }
    input_policy
}

fn add_iptables4(ctx: &Context, section: &mut AuditSection, evidence: Option<FamilyEvidence>) {
    let name = tr(ctx, "iptables (IPv4)");
    let row = match evidence {
        Some(FamilyEvidence::Restrictive) => AuditCheck::new(name, AuditStatus::Pass, tr(
            ctx,
            "iptables has a restrictive INPUT default policy; individual rules may allow exceptions.",
        )),
        Some(FamilyEvidence::Permissive) => AuditCheck::new(name, AuditStatus::Warning, tr(ctx, "iptables has a permissive INPUT default policy")),
        _ => AuditCheck::new(name, AuditStatus::Unknown, tr(ctx, "iptables INPUT policy could not be verified")),
    };
    section.push(row);
}

fn add_iptables6(ctx: &Context, section: &mut AuditSection, evidence: Option<FamilyEvidence>) {
    let name = tr(ctx, "iptables (IPv6)");
    let row = match evidence {
        Some(FamilyEvidence::Restrictive) => AuditCheck::new(name, AuditStatus::Pass, tr(
            ctx,
            "ip6tables has a restrictive INPUT default policy; individual rules may allow exceptions.",
        )),
        Some(FamilyEvidence::Permissive) => AuditCheck::new(name, AuditStatus::Warning, tr(ctx, "ip6tables has a permissive INPUT default policy")),
        _ => AuditCheck::new(name, AuditStatus::Unknown, tr(ctx, "ip6tables INPUT policy could not be verified")),
    };
    section.push(row);
}

fn manager_overlap(ufw: UfwState, firewalld: FirewalldOwner) -> bool {
    matches!(ufw, UfwState::Active { .. }) && firewalld == FirewalldOwner::Present
}

fn add_gufw(ctx: &Context, section: &mut AuditSection, present: bool) {
    let name = tr(ctx, "Gufw");
    let mut row = if present {
        AuditCheck::new(name, AuditStatus::Pass, tr(ctx, "Gufw is available."))
    } else {
        AuditCheck::new(name, AuditStatus::Skipped, tr(
            ctx,
            "Gufw was not confirmed; this optional inventory does not affect firewall policy analysis.",
        ))
    };
    row.optional_missing = !present;
    if present {
        row.launch_command = Some("gufw".to_owned());
        row.launch_label = Some(tr(ctx, "Open Gufw"));
    }
    section.push(row);
}

fn add_firewall_config(ctx: &Context, section: &mut AuditSection, present: bool) {
    let name = tr(ctx, "Firewall Config");
    let mut row = if present {
        AuditCheck::new(
            name,
            AuditStatus::Pass,
            tr(ctx, "Firewall Config is available."),
        )
    } else {
        AuditCheck::new(name, AuditStatus::Skipped, tr(
            ctx,
            "Firewall Config was not confirmed; this optional inventory does not affect firewall policy analysis.",
        ))
    };
    row.optional_missing = !present;
    if present {
        row.launch_command = Some("firewall-config".to_owned());
        row.launch_label = Some(tr(ctx, "Open Firewall Config"));
    }
    section.push(row);
}

fn plasma_firewall_installed() -> bool {
    ["plasma-firewall", "plasma5-firewall", "plasma6-firewall"]
        .into_iter()
        .any(package_installed)
}

fn package_installed(package: &str) -> bool {
    let dpkg = probe("dpkg", &["-s", package]);
    if usable(&dpkg) && dpkg_status_installed(&dpkg.stdout) {
        return true;
    }
    let rpm = probe("rpm", &["-q", "--", package]);
    if usable(&rpm) {
        return true;
    }
    let pacman = probe("pacman", &["-Q", "--", package]);
    usable(&pacman)
}

fn dpkg_status_installed(text: &str) -> bool {
    text.lines().any(|line| {
        let Some(status) = line.strip_prefix("Status: ") else {
            return false;
        };
        let mut fields = status.split_whitespace();
        let _want = fields.next();
        let error = fields.next();
        let state = fields.next();
        error == Some("ok") && state == Some("installed") && fields.next().is_none()
    })
}

fn add_plasma_firewall(ctx: &Context, section: &mut AuditSection, installed: bool) {
    let name = tr(ctx, "Plasma Firewall");
    let mut row = if installed {
        AuditCheck::new(
            name,
            AuditStatus::Pass,
            tr(
                ctx,
                "Plasma Firewall is installed; it manages an existing firewall backend.",
            ),
        )
    } else {
        AuditCheck::new(
            name,
            AuditStatus::Skipped,
            tr(
                ctx,
                "Plasma Firewall was not confirmed; it is only a management module.",
            ),
        )
    };
    row.optional_missing = !installed;
    section.push(row);
}

fn nft_status(assessment: NativeAssessment) -> AuditStatus {
    if assessment.ipv4 == FamilyEvidence::Restrictive
        && assessment.ipv6 == FamilyEvidence::Restrictive
    {
        AuditStatus::Pass
    } else if matches!(assessment.ipv4, FamilyEvidence::Permissive)
        || matches!(assessment.ipv6, FamilyEvidence::Permissive)
    {
        AuditStatus::Warning
    } else {
        AuditStatus::Unknown
    }
}

fn probe_is_usable(
    code: Option<i32>,
    timed_out: bool,
    truncated: bool,
    invalid_utf8: bool,
) -> bool {
    code == Some(0) && !timed_out && !truncated && !invalid_utf8
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::common::Paths;
    use tempfile::TempDir;

    fn completed_output(bytes: Vec<u8>) -> LimitedCommandOutput {
        let (stdout, invalid_utf8) = crate::host_probe::limited_output_text(bytes);
        LimitedCommandOutput {
            code: Some(0),
            stdout,
            timed_out: false,
            truncated: false,
            invalid_utf8,
        }
    }

    fn test_context(temp: &TempDir) -> Context {
        Context::with_paths(Paths {
            home: temp.path().join("home"),
            config_dir: temp.path().join("config"),
            data_dir: temp.path().join("data"),
        })
        .expect("create test context")
    }

    fn nft_consumer_status(ctx: &Context, assessment: Option<NativeAssessment>) -> AuditStatus {
        let mut section = AuditSection::new(
            ctx,
            AuditCategory::Firewall,
            "Firewall",
            "security-medium-symbolic",
        );
        add_nftables(ctx, &mut section, assessment);
        section.checks.pop().expect("nftables row").status
    }

    #[test]
    fn trusted_ufw_path_rejects_unsafe_owners_modes_and_symlink_resolution() {
        let mut entries = BTreeMap::from([
            ("/", (0, 0o040755)),
            ("/usr", (0, 0o040755)),
            ("/usr/sbin", (0, 0o040755)),
            ("/usr/sbin/ufw", (0, 0o120777)),
            ("/usr/lib", (0, 0o040755)),
            ("/usr/lib/ufw", (0, 0o100755)),
            ("/tmp", (0, 0o041777)),
        ]);
        let trusted = |entries: &BTreeMap<&str, (u32, u32)>, target: &str| {
            trusted_path_with(
                "/usr/sbin/ufw",
                |path| entries.get(path.to_str()?).copied(),
                |_| Some(target.to_owned()),
            )
        };
        assert!(trusted(&entries, "../lib/ufw"));
        assert!(!trusted(&entries, "/tmp/ufw"));
        assert!(!trusted(&entries, "/usr/sbin/ufw"));
        entries.insert("/usr/lib/ufw", (1000, 0o100755));
        assert!(!trusted(&entries, "../lib/ufw"));
        entries.insert("/usr/lib/ufw", (0, 0o100775));
        assert!(!trusted(&entries, "../lib/ufw"));
        entries.insert("/usr/lib/ufw", (0, 0o100757));
        assert!(!trusted(&entries, "../lib/ufw"));
        entries.insert("/usr/lib/ufw", (0, 0o100644));
        assert!(!trusted(&entries, "../lib/ufw"));
        entries.insert("/usr/lib/ufw", (0, 0o100755));
        entries.insert("/usr/lib", (0, 0o040775));
        assert!(!trusted(&entries, "../lib/ufw"));
        entries.insert("/usr/lib", (0, 0o040755));
        entries.insert("/usr/sbin/ufw", (1000, 0o120777));
        assert!(!trusted(&entries, "../lib/ufw"));
    }

    #[test]
    fn ufw_admin_action_requires_unknown_state_and_trusted_executable() {
        let temp = TempDir::new().expect("create temporary context root");
        let ctx = test_context(&temp);
        let mut section = AuditSection::new(
            &ctx,
            AuditCategory::Firewall,
            "Firewall",
            "security-medium-symbolic",
        );
        add_ufw(&ctx, &mut section, UfwState::Unknown, || false);
        add_ufw(&ctx, &mut section, UfwState::Unknown, || true);
        add_ufw(&ctx, &mut section, UfwState::Inactive, || true);

        assert_eq!(section.checks[0].launch_command, None);
        assert_eq!(section.checks[0].recommendation, None);
        assert_eq!(
            section.checks[1].launch_command.as_deref(),
            Some("__ufw_status__")
        );
        assert_eq!(
            section.checks[1].launch_label.as_deref(),
            Some("Check UFW with administrator access")
        );
        assert_eq!(section.checks[2].launch_command, None);
    }

    #[test]
    fn authenticated_ufw_output_controls_returned_and_emitted_firewall_rows() {
        use std::sync::{Arc, Mutex};

        let temp = TempDir::new().expect("create temporary context root");
        let events = Arc::new(Mutex::new(Vec::new()));
        let received = Arc::clone(&events);
        let ctx = test_context(&temp).with_emitter(move |event| {
            received.lock().expect("event lock").push(event);
        });
        for (output, expected) in [
            (
                "Status: active\nDefault: deny (incoming), allow (outgoing)\n",
                AuditStatus::Pass,
            ),
            (
                "Status: active\nDefault: reject (incoming), allow (outgoing)\n",
                AuditStatus::Pass,
            ),
            (
                "Status: active\nDefault: allow (incoming), allow (outgoing)\n",
                AuditStatus::Warning,
            ),
            ("Status: inactive\n", AuditStatus::Warning),
        ] {
            let result = finish_ufw_status(
                &ctx,
                &completed_output(output.as_bytes().to_vec()),
                |state| {
                    let mut section = AuditSection::new(
                        &ctx,
                        AuditCategory::Firewall,
                        "Firewall",
                        "security-medium-symbolic",
                    );
                    add_ufw(&ctx, &mut section, state, || false);
                    section
                },
            )
            .expect("valid UFW status");
            assert_eq!(result["cancelled"], false);
            let section: AuditSection =
                serde_json::from_value(result["section"].clone()).expect("section");
            assert_eq!(section.category, AuditCategory::Firewall);
            assert_eq!(section.checks[0].status, expected);
            assert_eq!(section.overall_status, expected);
            let mut events = events.lock().expect("event lock");
            let event = events.pop().expect("progress event");
            assert_eq!(event.event, "audit-progress");
            assert_eq!(event.data["section"], result["section"]);
            assert!(events.is_empty());
        }
    }

    #[test]
    fn authenticated_ufw_cancellation_denial_and_bad_output_never_emit_sections() {
        use std::sync::{Arc, Mutex};

        let temp = TempDir::new().expect("create temporary context root");
        let events = Arc::new(Mutex::new(Vec::new()));
        let received = Arc::clone(&events);
        let ctx = test_context(&temp).with_emitter(move |event| {
            received.lock().expect("event lock").push(event);
        });
        let mut output = completed_output(b"Status: active\nDefault: deny (incoming)\n".to_vec());
        output.code = Some(126);
        let cancelled = finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild"));
        assert_eq!(
            cancelled.expect("cancelled"),
            serde_json::json!({"cancelled": true})
        );

        output.code = Some(127);
        assert_eq!(
            finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).unwrap_err(),
            "Administrator authorization for the UFW status check was denied or unavailable."
        );
        output.code = Some(1);
        assert_eq!(
            finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).unwrap_err(),
            "The UFW status check failed."
        );
        output.code = Some(0);
        output.timed_out = true;
        assert_eq!(
            finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).unwrap_err(),
            "The UFW status check timed out."
        );
        output.timed_out = false;
        output.truncated = true;
        assert_eq!(
            finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).unwrap_err(),
            "The UFW status check returned incomplete or invalid output."
        );
        output.truncated = false;
        output.invalid_utf8 = true;
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        output.invalid_utf8 = false;
        output.code = None;
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        output.code = Some(0);
        output.stdout = "Status: active-ish\n".to_owned();
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        output.stdout = "Status: active\n".to_owned();
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        output.stdout = "Status: active\nDefault: deny (incoming)\n\0".to_owned();
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        output.stdout =
            "Status: active\nDefault: deny (incoming)\nDefault: allow (incoming)\n".to_owned();
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        output.stdout = "Status: active\nDefault: deny (incoming), allow (incoming)\n".to_owned();
        assert!(finish_ufw_status(&ctx, &output, |_| panic!("must not rebuild")).is_err());
        assert!(events.lock().expect("event lock").is_empty());
    }

    #[test]
    fn optional_missing_marks_only_unconfirmed_management_inventory() {
        let temp = TempDir::new().expect("create temporary context root");
        let ctx = test_context(&temp);
        let mut section = AuditSection::new(
            &ctx,
            AuditCategory::Firewall,
            "Firewall",
            "security-medium-symbolic",
        );

        for present in [false, true] {
            add_gufw(&ctx, &mut section, present);
            add_firewall_config(&ctx, &mut section, present);
            add_plasma_firewall(&ctx, &mut section, present);
        }
        add_ufw(&ctx, &mut section, UfwState::Inactive, || false);
        add_ufw(&ctx, &mut section, UfwState::Unknown, || false);
        add_nftables(&ctx, &mut section, None);

        assert!(section.checks[..3].iter().all(|row| row.optional_missing));
        assert!(section.checks[3..].iter().all(|row| !row.optional_missing));
    }

    #[test]
    fn ufw_requires_an_exact_successful_status_header() {
        assert_eq!(
            parse_ufw_status("Status: active\nDefault: deny (incoming), allow (outgoing)\n"),
            UfwState::Active {
                incoming: InputPolicy::Deny,
                listed_exceptions: false,
            }
        );
        assert_eq!(parse_ufw_status("Status: inactive\n"), UfwState::Inactive);
        assert_eq!(
            parse_ufw_status("Status: active-ish\nDefault: deny (incoming)\n"),
            UfwState::Unknown
        );
        assert_eq!(
            parse_ufw_status("Status: active\nStatus: inactive\n"),
            UfwState::Unknown
        );
    }

    #[test]
    fn active_ufw_without_default_policy_is_not_a_pass() {
        assert_eq!(
            parse_ufw_status("Status: active\nTo Action From\n22/tcp ALLOW IN Anywhere\n"),
            UfwState::Active {
                incoming: InputPolicy::Unverified,
                listed_exceptions: true,
            }
        );
    }

    #[test]
    fn ipv6_only_ufw_exception_qualifies_the_consumer_row() {
        let temp = TempDir::new().expect("create temporary context root");
        let ctx = test_context(&temp);
        let with_ipv6_exception = inspect_ufw(&completed_output(
            b"Status: active\nDefault: deny (incoming), allow (outgoing)\nTo Action From\n22/tcp (v6) ALLOW IN Anywhere (v6)\n"
                .to_vec(),
        ));
        let without_exception = inspect_ufw(&completed_output(
            b"Status: active\nDefault: deny (incoming), allow (outgoing)\n".to_vec(),
        ));

        let mut qualified = AuditSection::new(
            &ctx,
            AuditCategory::Firewall,
            "Firewall",
            "security-medium-symbolic",
        );
        add_ufw(&ctx, &mut qualified, with_ipv6_exception, || false);
        let qualified = qualified.checks.pop().expect("qualified UFW row");

        let mut unqualified = AuditSection::new(
            &ctx,
            AuditCategory::Firewall,
            "Firewall",
            "security-medium-symbolic",
        );
        add_ufw(&ctx, &mut unqualified, without_exception, || false);
        let unqualified = unqualified.checks.pop().expect("unqualified UFW row");

        assert_eq!(qualified.status, AuditStatus::Pass);
        assert_eq!(unqualified.status, AuditStatus::Pass);
        assert_ne!(qualified.detail, unqualified.detail);
    }

    #[test]
    fn raw_control_or_invalid_utf8_output_cannot_be_repaired_into_firewall_evidence() {
        let ufw = completed_output(
            b"Status: ac\0tive\nDefault: deny (incoming), allow (outgoing)\n".to_vec(),
        );
        assert_eq!(inspect_ufw(&ufw), UfwState::Unknown);

        let mut nft = br#"{"nftables":[{"chain":{"family":"inet","table":"filter","name":"input","type":"filter","hook":"input","policy":"drop"}}]}"#.to_vec();
        nft.push(0);
        assert!(inspect_nft(&completed_output(nft)).is_none());

        let invalid_utf8 = completed_output(b"Status: active\n\xff".to_vec());
        assert_eq!(inspect_ufw(&invalid_utf8), UfwState::Unknown);
    }

    #[test]
    fn firewalld_bus_owner_requires_the_verified_boolean_shape() {
        assert_eq!(
            parse_firewalld_owner(r#"{"type":"b","data":[true]}"#),
            FirewalldOwner::Present
        );
        assert_eq!(
            parse_firewalld_owner(r#"{"type":"b","data":[false]}"#),
            FirewalldOwner::Absent
        );
        assert_eq!(
            parse_firewalld_owner(r#"{"type":"b","data":true}"#),
            FirewalldOwner::Unknown
        );
        assert_eq!(
            parse_firewalld_owner(r#"{"type":"s","data":["true"]}"#),
            FirewalldOwner::Unknown
        );
    }

    #[test]
    fn overlap_is_only_a_potential_manager_warning() {
        let active = UfwState::Active {
            incoming: InputPolicy::Deny,
            listed_exceptions: false,
        };
        assert!(manager_overlap(active, FirewalldOwner::Present));
        assert!(!manager_overlap(
            UfwState::Inactive,
            FirewalldOwner::Present
        ));
        assert!(!manager_overlap(active, FirewalldOwner::Absent));
    }

    #[test]
    fn nft_ignores_nat_forward_named_input_and_dormant_chains() {
        let assessment = parse_nft_ruleset(
            r#"{"nftables":[
                {"table":{"family":"ip","name":"filter"}},
                {"table":{"family":"ip","name":"sleep","flags":["dormant"]}},
                {"chain":{"family":"ip","table":"nat","name":"prerouting","type":"nat","hook":"prerouting","policy":"accept"}},
                {"chain":{"family":"ip","table":"filter","name":"forward","type":"filter","hook":"forward","policy":"accept"}},
                {"chain":{"family":"ip","table":"filter","name":"input","policy":"drop"}},
                {"chain":{"family":"ip","table":"sleep","name":"sleeping","type":"filter","hook":"input","policy":"drop"}},
                {"chain":{"family":"ip","table":"filter","name":"live","type":"filter","hook":"input","prio":0,"policy":"drop"}}
            ]}"#,
        )
        .expect("valid nft JSON");
        assert_eq!(assessment.ipv4, FamilyEvidence::Restrictive);
        assert_eq!(assessment.ipv6, FamilyEvidence::Absent);
    }

    #[test]
    fn nft_complete_inet_base_chain_covers_both_families() {
        let ruleset = r#"{"nftables":[
            {"table":{"family":"inet","name":"filter"}},
            {"chain":{"family":"inet","table":"filter","name":"input","type":"filter","hook":"input","prio":0,"policy":"drop"}}
        ]}"#;
        let assessment = parse_nft_ruleset(ruleset).expect("complete nft base chain");
        assert_eq!(assessment.ipv4, FamilyEvidence::Restrictive);
        assert_eq!(assessment.ipv6, FamilyEvidence::Restrictive);

        let temp = TempDir::new().expect("create temporary context root");
        let ctx = test_context(&temp);
        assert_eq!(
            nft_consumer_status(
                &ctx,
                inspect_nft(&completed_output(ruleset.as_bytes().to_vec()))
            ),
            AuditStatus::Pass
        );
    }

    #[test]
    fn nft_incomplete_base_chain_evidence_is_unknown_to_consumers() {
        let temp = TempDir::new().expect("create temporary context root");
        let ctx = test_context(&temp);
        for ruleset in [
            r#"{"nftables":[{"chain":{"family":"inet","name":"input","type":"filter","hook":"input","prio":0,"policy":"drop"}}]}"#,
            r#"{"nftables":[{"chain":{"family":"inet","table":"filter","name":"input","type":"filter","hook":"input","prio":0,"policy":"drop"}}]}"#,
            r#"{"nftables":[{"table":{"family":"inet","name":"filter"}},{"chain":{"family":"inet","table":"filter","type":"filter","hook":"input","prio":0,"policy":"drop"}}]}"#,
            r#"{"nftables":[{"table":{"family":"inet","name":"filter"}},{"chain":{"family":"inet","table":"filter","name":"input","type":"filter","hook":"input","policy":"drop"}}]}"#,
            r#"{"nftables":[{"table":{"family":"inet","name":"filter"}},{"chain":{"family":"inet","table":"filter","name":"input","type":"filter","hook":"input","prio":0,"policy":"reject"}}]}"#,
            r#"{"nftables":[{"table":{"family":"inet","name":"filter"}},{"chain":{"family":"inet","table":"filter","name":"valid","type":"filter","hook":"input","prio":0,"policy":"drop"}},{"chain":{"family":"inet","table":"filter","name":"invalid","type":"filter","hook":"input","policy":"drop"}}]}"#,
        ] {
            let assessment = inspect_nft(&completed_output(ruleset.as_bytes().to_vec()));
            assert_eq!(
                nft_consumer_status(&ctx, assessment),
                AuditStatus::Unknown,
                "incomplete base-chain evidence must not be reported as protected"
            );
        }
    }

    #[test]
    fn nft_malformed_or_single_family_evidence_never_claims_full_coverage() {
        let temp = TempDir::new().expect("create temporary context root");
        let ctx = test_context(&temp);
        assert_eq!(
            nft_consumer_status(&ctx, inspect_nft(&completed_output(b"not json".to_vec()))),
            AuditStatus::Unknown
        );
        assert_eq!(
            nft_consumer_status(
                &ctx,
                inspect_nft(&completed_output(
                    br#"{"nftables":[{"chain":"malformed"}]}"#.to_vec()
                ))
            ),
            AuditStatus::Unknown
        );
        let single = NativeAssessment {
            ipv4: FamilyEvidence::Restrictive,
            ipv6: FamilyEvidence::Absent,
        };
        assert_ne!(
            nft_consumer_status(&ctx, Some(single)),
            AuditStatus::Pass,
            "single-family evidence cannot establish IPv4 and IPv6 coverage"
        );
    }

    #[test]
    fn iptables_requires_a_complete_filter_table_and_a_valid_input_policy() {
        assert_eq!(
            parse_iptables_save("*filter\n:INPUT DROP [0:0]\n:FORWARD ACCEPT [0:0]\nCOMMIT\n"),
            Some(FamilyEvidence::Restrictive)
        );
        assert_eq!(
            parse_iptables_save("*filter\n:INPUT ACCEPT [0:0]\n:FORWARD DROP [0:0]\nCOMMIT\n"),
            Some(FamilyEvidence::Permissive)
        );
        assert_eq!(
            parse_iptables_save(
                "*nat\n:PREROUTING ACCEPT [0:0]\nCOMMIT\n*filter\n:FORWARD DROP [0:0]\nCOMMIT\n"
            ),
            None
        );
        assert_eq!(parse_iptables_save("*filter\n:INPUT DROP [0:0]\n"), None);
        assert_eq!(
            parse_iptables_save("*filter\n:INPUT REJECT [0:0]\nCOMMIT\n"),
            None
        );
        assert_eq!(
            parse_iptables_save("*filter\n:INPUT DROP [0:0]\n:INPUT DROP [0:0]\nCOMMIT\n"),
            None
        );
        let ipv4 = parse_iptables_save("*filter\n:INPUT DROP [0:0]\nCOMMIT\n");
        let ipv6 = parse_iptables_save("*filter\n:INPUT ACCEPT [0:0]\nCOMMIT\n");
        assert_eq!(ipv4, Some(FamilyEvidence::Restrictive));
        assert_eq!(ipv6, Some(FamilyEvidence::Permissive));
    }
    #[test]
    fn incomplete_probe_evidence_is_not_accepted() {
        assert!(!probe_is_usable(Some(1), false, false, false));
        assert!(!probe_is_usable(Some(0), true, false, false));
        assert!(!probe_is_usable(Some(0), false, true, false));
        assert!(!probe_is_usable(Some(0), false, false, true));
        assert!(probe_is_usable(Some(0), false, false, false));
    }

    #[test]
    fn plasma_package_inventory_accepts_held_installs_only_with_ok_installed_state() {
        assert!(dpkg_status_installed(
            "Package: plasma-firewall\nStatus: hold ok installed\n"
        ));
        assert!(dpkg_status_installed(
            "Package: plasma-firewall\nStatus: install ok installed\n"
        ));
        assert!(!dpkg_status_installed(
            "Package: plasma-firewall\nStatus: deinstall ok config-files\n"
        ));
        assert!(!dpkg_status_installed(
            "Package: plasma-firewall\nStatus: install reinstreq installed\n"
        ));
        assert!(!dpkg_status_installed("Status: install ok\n"));
    }
}
