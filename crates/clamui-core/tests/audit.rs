use std::time::{Duration, UNIX_EPOCH};

use clamui_core::audit::{
    overall_status, parse_cvd_age, parse_sshd_file, parse_sshd_output, portmaster_module_status,
    AuditCheck, AuditStatus,
};
use clamui_core::portmaster::{parse_authorization_response, parse_modules_status};

fn audit_check(status: AuditStatus) -> AuditCheck {
    AuditCheck {
        name: "fixture".to_owned(),
        status,
        detail: "fixture".to_owned(),
        recommendation: None,
        install_command: None,
        info_url: None,
        launch_command: None,
        launch_label: None,
    }
}

#[test]
fn audit_status_precedence_never_hides_a_failure() {
    assert_eq!(
        overall_status(&[
            audit_check(AuditStatus::Pass),
            audit_check(AuditStatus::Warning),
            audit_check(AuditStatus::Fail)
        ]),
        AuditStatus::Fail
    );
    assert_eq!(
        overall_status(&[
            audit_check(AuditStatus::Skipped),
            audit_check(AuditStatus::Checking)
        ]),
        AuditStatus::Skipped
    );
    assert_eq!(overall_status(&[]), AuditStatus::Unknown);
}

#[test]
fn cvd_header_parser_accepts_binary_payload_after_timestamp() {
    let timestamp = 1_700_000_000_u64;
    let mut fixture =
        format!("ClamAV-VDB:24 Jun 2026:27000:2000000:90:md5:dsig:builder:{timestamp}")
            .into_bytes();
    fixture.extend([0x1f, 0x8b, 0x08, 0, 0xff, 0x7f, 0x01]);

    let (age, date) = parse_cvd_age(
        &fixture,
        UNIX_EPOCH + Duration::from_secs(timestamp + 3 * 86_400),
    )
    .expect("fixture has a valid CVD header");
    assert_eq!(age, 3);
    assert_eq!(date, "24 Jun 2026");
    assert!(parse_cvd_age(b"not a CVD", UNIX_EPOCH).is_none());
}

#[test]
fn effective_sshd_output_keeps_each_directive() {
    let effective =
        parse_sshd_output("permitrootlogin no\npasswordauthentication yes\nx11forwarding yes\n");
    assert_eq!(effective["permitrootlogin"], "no");
    assert_eq!(effective["passwordauthentication"], "yes");
    assert_eq!(effective["x11forwarding"], "yes");
}

#[test]
fn sshd_file_parser_matches_first_value_and_match_scope_rules() {
    let config = parse_sshd_file(
        "PermitRootLogin no\nPermitRootLogin yes\nPasswordAuthentication no\nMatch User admin\nX11Forwarding yes\n",
    );
    assert_eq!(config["permitrootlogin"], "no");
    assert_eq!(config["passwordauthentication"], "no");
    assert!(!config.contains_key("x11forwarding"));
}

#[test]
fn portmaster_module_response_fixture_is_stable_and_sorted() {
    let rows = parse_modules_status(&serde_json::json!({
        "zebra": {"Status": "degraded", "FailureMsg": "waiting"},
        "core": {"status": "online"},
        "ignored": ["not", "an", "object"]
    }));
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].name, "core");
    assert_eq!(rows[0].status, "online");
    assert_eq!(rows[1].name, "zebra");
    assert_eq!(rows[1].failure_msg.as_deref(), Some("waiting"));
    assert_eq!(portmaster_module_status("online"), AuditStatus::Pass);
    assert_eq!(portmaster_module_status("failure"), AuditStatus::Fail);
    assert_eq!(portmaster_module_status("degraded"), AuditStatus::Warning);
    assert_eq!(portmaster_module_status("new-state"), AuditStatus::Unknown);
}

#[test]
fn portmaster_authorization_response_fixture_accepts_only_real_tokens() {
    assert_eq!(
        parse_authorization_response(r#"{"token":"approved-token"}"#).as_deref(),
        Some("approved-token")
    );
    assert_eq!(
        parse_authorization_response(r#"{"Token":"legacy-token"}"#).as_deref(),
        Some("legacy-token")
    );
    assert_eq!(
        parse_authorization_response(r#"{"status":"approved"}"#),
        None
    );
    assert_eq!(
        parse_authorization_response("plain-token\n").as_deref(),
        Some("plain-token")
    );
}
