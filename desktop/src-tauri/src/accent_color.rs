use futures_util::StreamExt;
use serde_json::json;
use std::{sync::Mutex, time::Duration};
use tauri::{AppHandle, Emitter, Manager};
use zbus::zvariant::{OwnedValue, Value};

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

pub(crate) fn init(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        if watch(&app).await.is_err() {
            log::warn!("System accent color portal is unavailable");
        }
    });
}

async fn watch(app: &AppHandle) -> zbus::Result<()> {
    let connection = tokio::time::timeout(PORTAL_TIMEOUT, async {
        zbus::connection::Builder::session()?
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
        .call::<_, _, OwnedValue>("Read", &(APPEARANCE, ACCENT_COLOR))
        .await
    {
        Ok(value) => publish(app, value),
        Err(_) => log::warn!("System accent color setting is unavailable"),
    }

    while let Some(message) = changes.next().await {
        match message.body().deserialize::<(String, String, OwnedValue)>() {
            Ok((namespace, key, value)) if namespace == APPEARANCE && key == ACCENT_COLOR => {
                publish(app, value);
            }
            Ok(_) => {}
            Err(_) => log::warn!("System accent color signal has an invalid payload"),
        }
    }
    Ok(())
}

fn publish(app: &AppHandle, value: OwnedValue) {
    let Some(accent) = portal_color_to_hex(value) else {
        log::warn!("System accent color has an unsupported value");
        return;
    };
    let state = app.state::<AccentColor>();
    let Ok(mut current) = state.0.lock() else {
        log::warn!("System accent color state is unavailable");
        return;
    };
    *current = Some(accent.clone());
    if app
        .emit(
            "clamui-event",
            json!({"event": "accent-color-changed", "data": {"accent": accent}}),
        )
        .is_err()
    {
        log::warn!("Could not emit the system accent color");
    }
}

fn portal_color_to_hex(value: OwnedValue) -> Option<String> {
    let mut value = Value::from(value);
    // Read may wrap its result in an extra variant; SettingChanged does not.
    while let Value::Value(inner) = value {
        value = *inner;
    }
    let Value::Structure(rgb) = value else {
        return None;
    };
    // Validate the arity before conversion: zvariant's tuple conversion can panic
    // on a structure with too few fields.
    let [red, green, blue] = rgb.fields() else {
        return None;
    };
    rgb_to_hex([
        f64::try_from(red).ok()?,
        f64::try_from(green).ok()?,
        f64::try_from(blue).ok()?,
    ])
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
        let rgb = Value::from((0.0, 0.5, 1.0));
        let direct = rgb.try_to_owned().unwrap();
        let nested = Value::Value(Box::new(rgb)).try_to_owned().unwrap();
        assert_eq!(portal_color_to_hex(direct).as_deref(), Some("#0080ff"));
        assert_eq!(portal_color_to_hex(nested).as_deref(), Some("#0080ff"));
    }

    #[test]
    fn rejects_unset_and_wrong_dbus_types() {
        for value in [
            Value::from((-1.0, -1.0, -1.0)),
            Value::from((1u32, 0u32, 0u32)),
            Value::from("blue"),
            Value::from((0.0, 1.0)),
        ] {
            assert_eq!(portal_color_to_hex(value.try_to_owned().unwrap()), None);
        }
    }
}
