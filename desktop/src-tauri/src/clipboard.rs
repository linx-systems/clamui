//! Clipboard access through the application's existing GDK display connection.

/// Must run on the GTK main thread, after Tauri initializes GTK.
pub(crate) fn write_text(text: &str) -> Result<(), String> {
    // GTK's string API cannot represent embedded NULs. Reject them before the
    // binding constructs a C string rather than panicking in the UI thread.
    if text.contains('\0') {
        return Err("clipboard text contains a NUL character".into());
    }
    let display = gtk::gdk::Display::default()
        .ok_or_else(|| "application display is unavailable".to_owned())?;
    let clipboard = gtk::Clipboard::default(&display)
        .ok_or_else(|| "application clipboard is unavailable".to_owned())?;
    clipboard.set_text(text);
    Ok(())
}
