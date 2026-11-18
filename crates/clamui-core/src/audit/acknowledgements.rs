use super::{overall_status, AuditSection};
use crate::common::{atomic_write, now_iso, Context};
use crate::AppResult;
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::ErrorKind;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

const FILE_NAME: &str = "audit_acknowledgements.json";

#[derive(Deserialize, Serialize)]
struct Acknowledgement {
    fingerprint: String,
    acknowledged_at: String,
}

type Records = BTreeMap<String, Acknowledgement>;

// Lock the read-modify-write transaction across contexts and processes. Atomic
// replacement alone would allow a scan to overwrite a concurrent user action.
fn update<T>(
    ctx: &Context,
    operation: impl FnOnce(&mut Records) -> AppResult<(T, bool)>,
) -> AppResult<T> {
    fs::create_dir_all(&ctx.paths.config_dir).map_err(|error| error.to_string())?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(ctx.paths.config_dir.join("audit_acknowledgements.lock"))
        .map_err(|error| format!("Failed to open audit acknowledgements lock: {error}"))?;
    lock.set_permissions(fs::Permissions::from_mode(0o600))
        .map_err(|error| error.to_string())?;
    lock.lock_exclusive()
        .map_err(|error| format!("Failed to lock audit acknowledgements: {error}"))?;
    let path = ctx.paths.config_dir.join(FILE_NAME);
    let mut records = match fs::read(&path) {
        Ok(bytes) => serde_json::from_slice::<Records>(&bytes)
            .map_err(|error| format!("Failed to parse audit acknowledgements: {error}"))?,
        Err(error) if error.kind() == ErrorKind::NotFound => Records::new(),
        Err(error) => return Err(format!("Failed to read audit acknowledgements: {error}")),
    };
    let (result, changed) = operation(&mut records)?;
    if changed {
        let bytes = serde_json::to_vec_pretty(&records).map_err(|error| error.to_string())?;
        atomic_write(&path, &bytes, 0o600)?;
    }
    Ok(result)
}

pub(super) fn apply(ctx: &Context, section: &mut AuditSection) -> AppResult<()> {
    update(ctx, |records| {
        let mut changed = false;
        for check in &mut section.checks {
            // Recompute after construction so later detail changes are covered.
            check.fingerprint = check.result_fingerprint();
            check.acknowledged = records
                .get(&check.id)
                .is_some_and(|record| record.fingerprint == check.fingerprint);
            if !check.acknowledged && records.remove(&check.id).is_some() {
                changed = true;
            }
        }
        section.overall_status = overall_status(&section.checks);
        Ok(((), changed))
    })
}

pub(super) fn dispatch(ctx: &Context, action: &str, args: &Value) -> AppResult<Value> {
    let id = args
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| {
            !id.is_empty()
                && id.len() <= 8192
                && id
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
        })
        .ok_or_else(|| "Audit acknowledgement requires a snake_case id".to_owned())?;
    let fingerprint = if action == "acknowledge" {
        Some(
            args.get("fingerprint")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty() && value.len() <= 131_072)
                .ok_or_else(|| {
                    "Audit acknowledgement requires a nonempty fingerprint".to_owned()
                })?,
        )
    } else {
        None
    };
    update(ctx, |records| {
        let changed = if let Some(fingerprint) = fingerprint {
            records.insert(
                id.to_owned(),
                Acknowledgement {
                    fingerprint: fingerprint.to_owned(),
                    acknowledged_at: now_iso(),
                },
            );
            true
        } else {
            records.remove(id).is_some()
        };
        Ok((json!({"acknowledged": fingerprint.is_some()}), changed))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audit::{self, AuditCategory, AuditCheck, AuditStatus};
    use crate::common::Paths;
    use tempfile::TempDir;

    fn context(temp: &TempDir) -> Context {
        Context::with_paths(Paths {
            home: temp.path().join("home"),
            config_dir: temp.path().join("config"),
            data_dir: temp.path().join("data"),
        })
        .expect("test context")
    }

    fn section(ctx: &Context, status: AuditStatus, detail: &str) -> AuditSection {
        let mut section = AuditSection::new(ctx, AuditCategory::Firewall, "Firewall", "firewall");
        let mut row = AuditCheck::new("firewall", "Firewall".into(), status, detail.into());
        row.essential = true;
        section.push(row);
        section
    }

    fn acknowledge(ctx: &Context, section: &AuditSection) {
        assert_eq!(
            audit::dispatch(
                ctx,
                "acknowledge",
                json!({
                    "id": section.checks[0].id,
                    "fingerprint": section.checks[0].fingerprint,
                })
            )
            .expect("acknowledge"),
            json!({"acknowledged": true})
        );
    }

    #[test]
    fn acknowledgement_survives_reload_and_revoke_round_trip() {
        let temp = TempDir::new().expect("temporary directory");
        let ctx = context(&temp);
        let mut report = section(&ctx, AuditStatus::Warning, "Disabled");
        acknowledge(&ctx, &report);
        let reloaded = context(&temp);
        apply(&reloaded, &mut report).expect("apply persisted acknowledgement");
        assert!(report.checks[0].acknowledged);
        assert_eq!(report.overall_status, AuditStatus::Pass);
        let path = ctx.paths.config_dir.join(FILE_NAME);
        assert_eq!(
            fs::metadata(&path).expect("metadata").permissions().mode() & 0o777,
            0o600
        );
        let records: Records =
            serde_json::from_slice(&fs::read(path).expect("records")).expect("JSON");
        assert!(!records["firewall"].acknowledged_at.is_empty());
        for _ in 0..2 {
            assert_eq!(
                audit::dispatch(&reloaded, "revoke", json!({"id": "firewall"})).expect("revoke"),
                json!({"acknowledged": false})
            );
        }
        apply(&context(&temp), &mut report).expect("apply revoked state");
        assert!(!report.checks[0].acknowledged);
        assert_eq!(report.overall_status, AuditStatus::Warning);
    }

    #[test]
    fn changed_status_or_detail_clears_record_and_old_result_stays_unacknowledged() {
        let temp = TempDir::new().expect("temporary directory");
        let ctx = context(&temp);
        for (status, detail) in [
            (AuditStatus::Fail, "Disabled"),
            (AuditStatus::Warning, "Changed"),
        ] {
            let mut original = section(&ctx, AuditStatus::Warning, "Disabled");
            acknowledge(&ctx, &original);
            let mut changed = section(&ctx, status, detail);
            apply(&ctx, &mut changed).expect("apply changed result");
            assert!(!changed.checks[0].acknowledged);
            let records: Records = serde_json::from_slice(
                &fs::read(ctx.paths.config_dir.join(FILE_NAME)).expect("records"),
            )
            .expect("JSON");
            assert!(records.is_empty());
            apply(&context(&temp), &mut original).expect("old result");
            assert!(!original.checks[0].acknowledged);
        }
    }

    #[test]
    fn partial_report_preserves_other_sections_and_corrupt_records_are_not_overwritten() {
        let temp = TempDir::new().expect("temporary directory");
        let ctx = context(&temp);
        let mut report = section(&ctx, AuditStatus::Warning, "Disabled");
        acknowledge(&ctx, &report);
        let mut other = section(&ctx, AuditStatus::Warning, "Other");
        other.checks[0].id = "ssh_hardening".into();
        apply(&ctx, &mut other).expect("unrelated section");
        apply(&ctx, &mut report).expect("original section");
        assert!(report.checks[0].acknowledged);
        let path = ctx.paths.config_dir.join(FILE_NAME);
        fs::write(&path, b"invalid").expect("corrupt fixture");
        assert!(audit::dispatch(&ctx, "revoke", json!({"id": "firewall"})).is_err());
        assert_eq!(fs::read(&path).expect("read corrupt fixture"), b"invalid");
    }

    #[test]
    fn dispatch_rejects_invalid_arguments_without_creating_records() {
        let temp = TempDir::new().expect("temporary directory");
        let ctx = context(&temp);
        for args in [
            json!({}),
            json!({"id": "../audit"}),
            json!({"id": ""}),
            json!({"id": 1}),
            json!({"id": "firewall"}),
            json!({"id": "firewall", "fingerprint": ""}),
            json!({"id": "firewall", "fingerprint": false}),
        ] {
            assert!(audit::dispatch(&ctx, "acknowledge", args).is_err());
        }
        assert!(!ctx.paths.config_dir.join(FILE_NAME).exists());
    }
}
