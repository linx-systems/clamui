use crate::{i18n, AppResult, Context};
use serde_json::{json, Value};

const AUTHORS: &str = include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/../../AUTHORS"));

/// Routes the static About-dialog credits without exposing filesystem access.
pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    if action != "credits" {
        return Err(format!("Unknown app action: {action}"));
    }
    if !args.as_object().is_some_and(|object| object.is_empty()) {
        return Err("app.credits accepts no arguments".to_owned());
    }

    let translator_credits = i18n::translate(
        ctx,
        // Translators: replace with your name(s) and optionally <email> or a URL, one translator per line. Leave untranslated if you do not want to be credited.
        "translator-credits",
    );
    let translator_credits = translator_credits.trim();

    Ok(json!({
        "contributors": contributors(),
        "translator_credits": (!translator_credits.is_empty() && translator_credits != "translator-credits")
            .then_some(translator_credits),
    }))
}

fn contributors() -> Vec<&'static str> {
    AUTHORS
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .collect()
}
