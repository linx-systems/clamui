use clamui_core::common::Context;
use futures_util::StreamExt;
use serde_json::json;
use std::{sync::Mutex, time::Duration};
use tauri::{AppHandle, Emitter, Manager};
use zbus::{OwnedVariant, Variant};

const APPEARANCE: &str = "org.freedesktop.appearance";
const ACCENT_COLOR: &str = "accent-color";
const PORTAL_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Default)]
pub(crate) struct AccentColor(Mutex<Option<String>>);

impl AccentColor {
    // Replay through startup_state when the portal responds before the webview listens.
    pub(crate) fn current(&self) -> Option<String> {
        self.0.lock().ok().and_then(|accent| accent.clone())
    }
}

/// A portal accent value: a usable color, or the spec's explicit "no preference".
#[derive(Debug, PartialEq)]
enum PortalAccent {
    Color(String),
    Unset,
}

pub(crate) fn init(app: AppHandle, ctx: Context) {
    tauri::async_runtime::spawn(async move {
        if let Err(error) = watch(&app, &ctx).await {
            // Expected on desktops without the Settings portal; keep it out of default logs.
            debug(
                &ctx,
                "INFO",
                &format!("system accent color portal is unavailable: {error}"),
            );
        }
    });
}

async fn watch(app: &AppHandle, ctx: &Context) -> zbus::Result<()> {
    let connection = tokio::time::timeout(PORTAL_TIMEOUT, async {
        zbus::connection::Builder::session()
            .method_timeout(PORTAL_TIMEOUT)
            .build()
            .await
    })
    .await
    .map_err(|_| zbus::Error::Failure("Accent portal connection timed out".into()))??;
    let proxy = zbus::Proxy::new(
        &connection,
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Settings",
    )
    .await?;

    // Subscribe first so a change during Read stays queued for processing.
    let mut changes = proxy
        .receive_signal_with_args("SettingChanged", &[(0, APPEARANCE), (1, ACCENT_COLOR)])
        .await?;
    match proxy
        .call::<_, _, OwnedVariant>("Read", &(APPEARANCE, ACCENT_COLOR))
        .await
    {
        Ok(value) => publish(app, ctx, value),
        Err(error) => debug(
            ctx,
            "INFO",
            &format!("system accent color setting is unavailable: {error}"),
        ),
    }

    while let Some(message) = changes.next().await {
        match message
            .body()
            .deserialize::<(String, String, OwnedVariant)>()
        {
            Ok((namespace, key, value)) if namespace == APPEARANCE && key == ACCENT_COLOR => {
                publish(app, ctx, value);
            }
            Ok(_) => {}
            Err(error) => debug(
                ctx,
                "WARNING",
                &format!("system accent color signal has an invalid payload: {error}"),
            ),
        }
    }
    Ok(())
}

fn publish(app: &AppHandle, ctx: &Context, value: OwnedVariant) {
    let accent = match parse_portal_accent(value) {
        Some(PortalAccent::Color(hex)) => Some(hex),
        Some(PortalAccent::Unset) => None,
        None => {
            debug(
                ctx,
                "WARNING",
                "system accent color has an unsupported value",
            );
            return;
        }
    };
    match app.state::<AccentColor>().0.lock() {
        Ok(mut current) => current.clone_from(&accent),
        Err(_) => {
            debug(ctx, "WARNING", "system accent color state is unavailable");
            return;
        }
    }
    // `null` tells the frontend to fall back to its built-in accent.
    if app
        .emit(
            "clamui-event",
            json!({"event": "accent-color-changed", "data": {"accent": accent}}),
        )
        .is_err()
    {
        debug(ctx, "WARNING", "could not emit the system accent color");
    }
}

fn debug(ctx: &Context, level: &str, message: &str) {
    let _ = clamui_core::logs::write_debug(ctx, level, "accent-color", message);
}

fn parse_portal_accent(value: OwnedVariant) -> Option<PortalAccent> {
    let mut value = Variant::from(value);
    // Read may wrap its result in an extra variant; SettingChanged does not.
    while let Variant::Variant(inner) = value {
        value = *inner;
    }
    let Variant::Structure(rgb) = value else {
        return None;
    };
    // Validate the arity before conversion: zvariant's tuple conversion can panic
    // on a structure with too few fields.
    let [red, green, blue] = rgb.fields() else {
        return None;
    };
    let rgb = [
        f64::try_from(red).ok()?,
        f64::try_from(green).ok()?,
        f64::try_from(blue).ok()?,
    ];
    // The portal spec treats out-of-range channels (e.g. -1, -1, -1) as unset.
    Some(rgb_to_hex(rgb).map_or(PortalAccent::Unset, PortalAccent::Color))
}

fn rgb_to_hex(rgb: [f64; 3]) -> Option<String> {
    if rgb
        .iter()
        .any(|channel| !channel.is_finite() || !(0.0..=1.0).contains(channel))
    {
        return None;
    }
    let [red, green, blue] = rgb.map(|channel| (channel * 255.0).round() as u8);
    Some(format!("#{red:02x}{green:02x}{blue:02x}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_endpoints_and_rounds_channels() {
        for (rgb, expected) in [
            ([0.0, 0.0, 0.0], "#000000"),
            ([1.0, 1.0, 1.0], "#ffffff"),
            ([1.0, 0.5, 0.0], "#ff8000"),
            ([0.1, 0.2, 0.3], "#1a334d"),
        ] {
            assert_eq!(rgb_to_hex(rgb).as_deref(), Some(expected));
        }
    }

    #[test]
    fn preserves_every_eight_bit_channel() {
        for byte in 0..=255u8 {
            let channel = f64::from(byte) / 255.0;
            assert_eq!(
                rgb_to_hex([channel; 3]),
                Some(format!("#{byte:02x}{byte:02x}{byte:02x}"))
            );
        }
    }

    #[test]
    fn rejects_invalid_channels_in_every_position() {
        for invalid in [
            -1.0,
            -f64::EPSILON,
            1.0 + f64::EPSILON,
            f64::NAN,
            f64::INFINITY,
            f64::NEG_INFINITY,
        ] {
            for position in 0..3 {
                let mut rgb = [0.5; 3];
                rgb[position] = invalid;
                assert_eq!(rgb_to_hex(rgb), None);
            }
        }
    }

    #[test]
    fn parses_signal_and_nested_read_variants() {
        let rgb = Variant::from((0.0, 0.5, 1.0));
        let direct = rgb.try_to_owned().unwrap();
        let nested = Variant::Variant(Box::new(rgb)).try_to_owned().unwrap();
        let expected = Some(PortalAccent::Color("#0080ff".into()));
        assert_eq!(parse_portal_accent(direct), expected);
        assert_eq!(parse_portal_accent(nested), expected);
    }

    #[test]
    fn treats_out_of_range_rgb_as_unset() {
        for value in [
            Variant::from((-1.0, -1.0, -1.0)),
            Variant::from((0.5, 1.5, 0.5)),
            Variant::Variant(Box::new(Variant::from((-1.0, -1.0, -1.0)))),
        ] {
            assert_eq!(
                parse_portal_accent(value.try_to_owned().unwrap()),
                Some(PortalAccent::Unset)
            );
        }
    }

    #[test]
    fn rejects_wrong_dbus_types() {
        for value in [
            Variant::from((1u32, 0u32, 0u32)),
            Variant::from("blue"),
            Variant::from((0.0, 1.0)),
            Variant::from((0.0, 1.0, 0.5, 1.0)),
        ] {
            assert_eq!(parse_portal_accent(value.try_to_owned().unwrap()), None);
        }
    }
}
