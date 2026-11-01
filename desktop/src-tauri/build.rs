fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "request",
            "choose_paths",
            "save_export",
            "copy_text",
            "open_external",
            "open_path",
            "app_close",
            "startup_state",
        ]),
    ))
    .expect("failed to generate Tauri command bindings");
}
