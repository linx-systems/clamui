#![cfg(target_os = "linux")]

#[path = "../src/clipboard.rs"]
mod clipboard;

#[test]
#[ignore = "requires an isolated GTK display; run with xvfb-run -a cargo test -p clamui --test linux_clipboard -- --ignored"]
fn copies_using_the_existing_display_without_an_x11_fallback() {
    gtk::init().expect("GTK test display must be available");
    // The application has a display connection, but a separate clipboard
    // backend cannot open an X11 connection. Flatpak fallback-x11 on native
    // Wayland has the same restriction. This integration binary has one test
    // so environment changes cannot race other tests.
    std::env::remove_var("DISPLAY");
    std::env::remove_var("WAYLAND_DISPLAY");
    let display = gtk::gdk::Display::default().expect("connected application display");
    let selection = gtk::Clipboard::default(&display).expect("application clipboard");

    for text in ["sudo apt install fail2ban", "ClamUI\nGrüße 日本語", ""] {
        clipboard::write_text(text).expect("copy must succeed without an X11 fallback");
        assert_eq!(selection.wait_for_text().as_deref(), Some(text));
    }

    clipboard::write_text("previous clipboard contents").unwrap();
    assert!(clipboard::write_text("invalid\0text").is_err());
    assert_eq!(
        selection.wait_for_text().as_deref(),
        Some("previous clipboard contents")
    );
}
