pub type AppResult<T> = Result<T, String>;
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub mod audit;
pub mod cli;
pub mod common;
pub mod config;
pub mod credentials;
pub mod credits;
pub mod headless;
pub mod host;
mod host_probe;
pub mod i18n;
pub mod logs;
pub mod network;
pub mod platform;
pub mod portmaster;
pub mod privileged;
pub mod profiles;
pub mod quarantine;
pub mod scan_parser;
pub mod scanner;
pub mod scheduler;
pub mod settings;
pub mod threat;
pub mod updater;
pub mod virustotal;

pub use common::{Context, Event, Job, Paths};
use serde_json::Value;

/// Routes only documented ClamUI operations. It intentionally exposes no generic
/// process, filesystem, database, or shell execution primitive.
pub fn dispatch(ctx: &Context, operation: &str, args: Value) -> AppResult<Value> {
    let (domain, action) = operation
        .split_once('.')
        .filter(|(_, action)| !action.is_empty())
        .ok_or_else(|| format!("invalid operation: {operation}"))?;
    match domain {
        // Settings and log operations are deliberately excluded: diagnostic
        // writes read settings and write logs, so instrumenting either would
        // recurse through this boundary.
        "settings" => settings::dispatch(ctx, action, args),
        "app" => instrument(ctx, "app", || credits::dispatch(ctx, action, args)),
        "logs" => logs::dispatch(ctx, action, args),
        "profiles" => instrument(ctx, "profiles", || profiles::dispatch(ctx, action, args)),
        "scanner" => instrument(ctx, "scanner", || scanner::dispatch(ctx, action, args)),
        "updater" => instrument(ctx, "updater", || updater::dispatch(ctx, action, args)),
        "components" => instrument(ctx, "components", || host::dispatch(ctx, action, args)),
        "quarantine" => instrument(ctx, "quarantine", || {
            quarantine::dispatch(ctx, action, args)
        }),
        "virustotal" => instrument(ctx, "virustotal", || {
            virustotal::dispatch(ctx, action, args)
        }),
        "audit" => instrument(ctx, "audit", || audit::dispatch(ctx, action, args)),
        "network" => instrument(ctx, "network", || network::dispatch(ctx, action, args)),
        "config" => instrument(ctx, "config", || config::dispatch(ctx, action, args)),
        "scheduler" => instrument(ctx, "scheduler", || scheduler::dispatch(ctx, action, args)),
        "platform" => instrument(ctx, "platform", || platform::dispatch(ctx, action, args)),
        "i18n" => instrument(ctx, "i18n", || i18n::dispatch(ctx, action, args)),
        "privileged" => instrument(ctx, "privileged", || {
            privileged::dispatch(ctx, action, args)
        }),
        _ => Err(format!("unsupported operation domain: {domain}")),
    }
}

/// Emits privacy-safe lifecycle diagnostics around real backend operations.
/// The writer's failures are intentionally isolated from the user operation.
fn instrument(
    ctx: &Context,
    domain: &'static str,
    operation: impl FnOnce() -> AppResult<Value>,
) -> AppResult<Value> {
    let _ = logs::write_debug(
        ctx,
        "INFO",
        "clamui-core.dispatch",
        &format!("{domain} operation started"),
    );
    match operation() {
        Ok(result) => {
            let _ = logs::write_debug(
                ctx,
                "INFO",
                "clamui-core.dispatch",
                &format!("{domain} operation completed"),
            );
            Ok(result)
        }
        Err(error) => {
            let _ = logs::write_debug(
                ctx,
                "ERROR",
                "clamui-core.dispatch",
                &format!("{domain} operation failed"),
            );
            Err(error)
        }
    }
}
