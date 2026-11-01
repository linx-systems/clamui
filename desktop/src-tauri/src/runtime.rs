use crate::{
    model::{ChoosePathsOptions, ChosenPaths, CloseResult, SavedExport, StartupState},
    notifications::Notifications,
    policy::{decode_open_target, is_safe_external_url, select_close_action, CloseAction},
    tray::{TrayController, TrayEvent, TrayLabels},
};
use base64::{engine::general_purpose::STANDARD, Engine};
use clamui_core::{
    common::{path_from_wire, path_to_wire, Context, Event},
    dispatch,
    i18n::translate,
};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Condvar, Mutex,
    },
};
use tauri::{
    webview::NewWindowResponse, AppHandle, DragDropEvent, Emitter, Manager, RunEvent, State,
    WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_notification::{Action, ActionType, NotificationExt};

const CANONICAL_LINUX_APPLICATION_ID: &str = "io.github.linx_systems.ClamUI";

pub struct AppState {
    ctx: Context,
    initial: Mutex<StartupState>,
    active_jobs: RunningJobs,
    start_minimized_pending: AtomicBool,
    tray: Arc<TrayController>,
    monitor: Mutex<Option<clamui_core::platform::MonitorHandle>>,
    notifications: Notifications,
}

struct RunningJobs {
    entries: Mutex<HashMap<u64, String>>,
    next_token: AtomicU64,
    accepting: AtomicBool,
    idle: Condvar,
}

struct OperationGuard<'a> {
    jobs: &'a RunningJobs,
    token: u64,
}

impl RunningJobs {
    fn register(&self, action: String) -> Result<OperationGuard<'_>, String> {
        if !self.accepting.load(Ordering::Acquire) {
            return Err("ClamUI is shutting down".into());
        }
        let token = self.next_token.fetch_add(1, Ordering::Relaxed);
        let mut entries = self.entries.lock().expect("job state poisoned");
        if !self.accepting.load(Ordering::Acquire) {
            return Err("ClamUI is shutting down".into());
        }
        entries.insert(token, action);
        Ok(OperationGuard { jobs: self, token })
    }

    fn scan_active(&self) -> bool {
        self.entries
            .lock()
            .expect("job state poisoned")
            .values()
            .any(|action| action == "scanner.scan")
    }

    fn snapshot(&self) -> Vec<String> {
        self.entries
            .lock()
            .expect("job state poisoned")
            .iter()
            .map(|(token, action)| format!("{action}#{token}"))
            .collect()
    }

    fn freeze(&self) {
        self.accepting.store(false, Ordering::Release);
    }

    fn wait_until_idle(&self) {
        let mut entries = self.entries.lock().expect("job state poisoned");
        while !entries.is_empty() {
            entries = self.idle.wait(entries).expect("job state poisoned");
        }
    }
}

impl Drop for OperationGuard<'_> {
    fn drop(&mut self) {
        let mut entries = self.jobs.entries.lock().expect("job state poisoned");
        entries.remove(&self.token);
        if entries.is_empty() {
            self.jobs.idle.notify_all();
        }
    }
}

impl AppState {
    fn scan_active(&self) -> bool {
        self.active_jobs.scan_active()
    }

    fn shutdown(&self) {
        let _ = clamui_core::logs::write_debug(
            &self.ctx,
            "INFO",
            "native-runtime",
            "native runtime shutdown started",
        );
        self.active_jobs.freeze();
        if let Some(monitor) = self.monitor.lock().expect("monitor state poisoned").take() {
            monitor.stop();
        }
        self.ctx.cancel_all();
        self.active_jobs.wait_until_idle();
        self.tray.shutdown();
        let _ = clamui_core::logs::write_debug(
            &self.ctx,
            "INFO",
            "native-runtime",
            "native runtime shutdown completed",
        );
    }
}

pub fn run(arguments: Vec<String>) -> Result<(), String> {
    let targets = parse_startup_targets(
        &arguments,
        &env::current_dir().map_err(|error| error.to_string())?,
    )?;

    let mut tauri_context = tauri::generate_context!();
    tauri_context.config_mut().identifier = CANONICAL_LINUX_APPLICATION_ID.into();
    let app_slot: Arc<Mutex<Option<AppHandle>>> = Arc::new(Mutex::new(None));
    let slot_for_events = app_slot.clone();
    let ctx = Context::new()?.with_emitter(move |event: Event| {
        if let Some(app) = slot_for_events
            .lock()
            .expect("app handle poisoned")
            .as_ref()
        {
            let state = app.state::<AppState>();
            state.tray.apply_event(&event.event, &event.data);
            state
                .notifications
                .dispatch(&state.ctx, app, &event.event, &event.data);
            let _ = app.emit("clamui-event", event);
        }
    });

    let tray_events: TrayEvent = Arc::new({
        let slot = app_slot.clone();
        move |event, data| {
            if let Some(app) = slot.lock().expect("app handle poisoned").as_ref() {
                if event == "quit" {
                    app.exit(0);
                } else if event == "toggle-window" {
                    toggle_window(app);
                } else {
                    if event == "tray-availability" {
                        if data.get("available").and_then(Value::as_bool) == Some(true) {
                            apply_start_minimize(app);
                        } else if let Some(window) = app.get_webview_window("main") {
                            if !window.is_visible().unwrap_or(true) {
                                let _ = show_window(app);
                            }
                        }
                    }
                    let _ = app.emit("clamui-event", json!({ "event": event, "data": data }));
                    if event != "tray-availability" {
                        let _ = show_window(app);
                    }
                }
            }
        }
    });
    let tray = TrayController::start(
        tray_events,
        TrayLabels {
            show: "ClamUI".into(),
            quick_scan: translate(&ctx, "Quick Scan"),
            full_scan: translate(&ctx, "Full Scan"),
            home_folder: translate(&ctx, "Home Folder"),
            update_database: translate(&ctx, "Update Database"),
            scan_profile: translate(&ctx, "Scan Profile"),
            quit: translate(&ctx, "Quit"),
        },
        path_to_wire(&ctx.paths.home),
        tauri_context
            .default_window_icon()
            .expect("Tauri context must contain the bundled application icon"),
    );
    let state = AppState {
        ctx: ctx.clone(),
        initial: Mutex::new(StartupState {
            paths: targets.paths,
            virustotal: targets.virustotal,
            tray_available: false,
            version: env!("CARGO_PKG_VERSION").into(),
            active_jobs: Vec::new(),
        }),
        active_jobs: RunningJobs {
            entries: Mutex::new(HashMap::new()),
            next_token: AtomicU64::new(1),
            accepting: AtomicBool::new(true),
            idle: Condvar::new(),
        },
        start_minimized_pending: AtomicBool::new(false),
        tray,
        monitor: Mutex::new(None),
        notifications: Notifications::new(),
    };

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(move |app, args, cwd| {
            let args = forwarded_instance_args(args);
            let cwd = PathBuf::from(cwd);
            if let Ok(targets) = parse_startup_targets(&args, &cwd) {
                if !targets.paths.is_empty() {
                    let _ = app.emit(
                        "clamui-event",
                        json!({
                            "event": "open-targets",
                            "data": { "paths": targets.paths, "virustotal": targets.virustotal, "start": true }
                        }),
                    );
                    let _ = show_window(app);
                }
            }
        }))
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_notification::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            request,
            choose_paths,
            save_export,
            copy_text,
            open_external,
            open_path,
            app_close,
            startup_state
        ])
        .on_window_event(|window, event| match event {
            WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let _ = request_close(window.app_handle(), None, false);
            }
            WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. }) => {
                let paths = paths.iter().map(|path| path_to_wire(path)).collect::<Vec<_>>();
                let _ = window.emit(
                    "clamui-event",
                    json!({ "event": "dropped-targets", "data": { "paths": paths, "start": false } }),
                );
            }
            _ => {}
        })
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("ClamUI")
                .inner_size(900.0, 700.0)
                .min_inner_size(360.0, 480.0)
                .resizable(true)
                .on_navigation(allow_navigation)
                .on_new_window(|_, _| NewWindowResponse::Deny)
                .build()
                .map_err(|error| error.to_string())?;
            *app_slot.lock().expect("app handle poisoned") = Some(app.handle().clone());
            let state = app.state::<AppState>();
            let _ = clamui_core::logs::write_debug(
                &state.ctx,
                "INFO",
                "native-runtime",
                "native runtime startup completed",
            );
            install_notification_actions(app.handle(), &state.ctx);
            match clamui_core::platform::start_monitor(state.ctx.clone()) {
                Ok(handle) => *state.monitor.lock().expect("monitor state poisoned") = Some(handle),
                Err(error) => {
                    let _ = app.emit(
                        "clamui-event",
                        json!({
                            "event": "runtime-error",
                            "data": { "component": "device-monitor", "message": error }
                        }),
                    );
                    let _ = clamui_core::logs::write_debug(
                        &state.ctx,
                        "WARNING",
                        "native-runtime",
                        "device monitor startup failed",
                    );
                }
            }
            sync_profiles(&state.ctx, &state.tray);
            let startup = state
                .initial
                .lock()
                .expect("startup state poisoned")
                .clone();
            let start_minimized = state
                .ctx
                .settings()
                .ok()
                .and_then(|value| value.get("start_minimized").and_then(Value::as_bool))
                .unwrap_or(false);
            state.start_minimized_pending.store(
                start_minimized && startup.paths.is_empty(),
                Ordering::Release,
            );
            apply_start_minimize(app.handle());
            Ok(())
        });

    let app = builder
        .build(tauri_context)
        .map_err(|error| error.to_string())?;
    app.run(move |handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<AppState>().shutdown();
        }
    });
    Ok(())
}

#[tauri::command]
async fn request(state: State<'_, AppState>, action: String, args: Value) -> Result<Value, String> {
    let _operation = state.active_jobs.register(action.clone())?;
    let ctx = state.ctx.clone();
    let action_for_work = action.clone();
    let result =
        tauri::async_runtime::spawn_blocking(move || dispatch(&ctx, &action_for_work, args))
            .await
            .map_err(|error| format!("operation task failed: {error}"));
    let value = result??;
    if action.starts_with("profiles.") {
        sync_profiles(&state.ctx, &state.tray);
    }
    Ok(value)
}

#[tauri::command]
async fn choose_paths(
    state: State<'_, AppState>,
    window: tauri::WebviewWindow,
    options: ChoosePathsOptions,
) -> Result<ChosenPaths, String> {
    let _operation = state.active_jobs.register("native.choose_paths".into())?;
    let ChoosePathsOptions {
        title,
        multiple,
        directory,
        filters,
    } = options;
    let directory = directory.unwrap_or(false);
    let multiple = multiple.unwrap_or(true);
    let title = title.unwrap_or_else(|| {
        if directory {
            translate(&state.ctx, "Add Folders")
        } else {
            translate(&state.ctx, "Add Files")
        }
    });
    let mut dialog = rfd::FileDialog::new().set_parent(&window).set_title(title);
    for filter in filters.unwrap_or_default() {
        dialog = dialog.add_filter(filter.name, &filter.extensions);
    }
    tauri::async_runtime::spawn_blocking(move || {
        let paths = match (directory, multiple) {
            (true, true) => dialog.pick_folders().unwrap_or_default(),
            (true, false) => dialog.pick_folder().into_iter().collect(),
            (false, true) => dialog.pick_files().unwrap_or_default(),
            (false, false) => dialog.pick_file().into_iter().collect(),
        };
        Ok(ChosenPaths {
            paths: paths.into_iter().map(|path| path_to_wire(&path)).collect(),
        })
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn save_export(
    state: State<'_, AppState>,
    window: tauri::WebviewWindow,
    content: String,
    default_name: String,
    filters: Option<Vec<crate::model::FileFilter>>,
    encoding: Option<String>,
) -> Result<SavedExport, String> {
    let _operation = state.active_jobs.register("native.save_export".into())?;
    if Path::new(&default_name).components().count() != 1 || default_name.is_empty() {
        return Err("default export name must be a filename".into());
    }
    let bytes = match encoding.as_deref().unwrap_or("utf8") {
        "utf8" => content.into_bytes(),
        "base64" => STANDARD
            .decode(content)
            .map_err(|_| "invalid base64 export payload".to_owned())?,
        _ => return Err("unsupported export encoding".into()),
    };
    let mut dialog = rfd::FileDialog::new()
        .set_parent(&window)
        .set_title(translate(&state.ctx, "Export"))
        .set_file_name(&default_name);
    for filter in filters.unwrap_or_default() {
        dialog = dialog.add_filter(filter.name, &filter.extensions);
    }
    tauri::async_runtime::spawn_blocking(move || {
        let Some(destination) = dialog.save_file() else {
            return Ok(SavedExport {
                saved: false,
                path: None,
            });
        };
        std::fs::write(&destination, bytes)
            .map_err(|error| format!("failed to save export: {error}"))?;
        Ok(SavedExport {
            saved: true,
            path: Some(path_to_wire(&destination)),
        })
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn copy_text(state: State<'_, AppState>, app: AppHandle, text: String) -> Result<(), String> {
    let _operation = state.active_jobs.register("native.copy_text".into())?;
    tauri::async_runtime::spawn_blocking(move || {
        app.clipboard()
            .write_text(text)
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn open_external(state: State<'_, AppState>, url: String) -> Result<(), String> {
    let _operation = state.active_jobs.register("native.open_external".into())?;
    let url = is_safe_external_url(&url)?;
    tauri::async_runtime::spawn_blocking(move || {
        open::that(url.as_str()).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn open_path(state: State<'_, AppState>, path: String) -> Result<(), String> {
    let _operation = state.active_jobs.register("native.open_path".into())?;
    let path = path_from_wire(&path)?;
    let metadata =
        std::fs::symlink_metadata(&path).map_err(|_| "requested path does not exist".to_owned())?;
    if !metadata.file_type().is_file() && !metadata.file_type().is_dir() {
        return Err("requested path is not a regular file or directory".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        open::that(path).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
fn app_close(
    app: AppHandle,
    choice: Option<String>,
    remember: Option<bool>,
) -> Result<CloseResult, String> {
    request_close(&app, choice.as_deref(), remember.unwrap_or(false))
}

fn request_close(
    app: &AppHandle,
    requested: Option<&str>,
    remember: bool,
) -> Result<CloseResult, String> {
    if requested == Some("cancel") {
        return Ok(CloseResult {
            action: "prompt".into(),
        });
    }
    let state = app.state::<AppState>();
    let settings = state.ctx.settings()?;
    let action = select_close_action(
        state.scan_active(),
        state.tray.available(),
        settings.get("close_behavior").and_then(Value::as_str),
        requested,
    )?;
    if remember && matches!(requested, Some("minimize") | Some("quit")) {
        state
            .ctx
            .update_settings(json!({ "close_behavior": requested }))?;
    }
    match action {
        CloseAction::Hide => {
            if let Some(window) = app.get_webview_window("main") {
                window.hide().map_err(|error| error.to_string())?;
            }
            Ok(CloseResult {
                action: "hide".into(),
            })
        }
        CloseAction::Quit => {
            app.exit(0);
            Ok(CloseResult {
                action: "quit".into(),
            })
        }
        CloseAction::Prompt => {
            app.emit("clamui-event", json!({ "event": "close-requested", "data": { "scan_active": state.scan_active(), "tray_available": state.tray.available() } })).map_err(|error| error.to_string())?;
            Ok(CloseResult {
                action: "prompt".into(),
            })
        }
    }
}

#[tauri::command]
fn startup_state(state: State<'_, AppState>) -> StartupState {
    let mut startup = state
        .initial
        .lock()
        .expect("startup state poisoned")
        .clone();
    startup.tray_available = state.tray.available();
    startup.active_jobs = state.active_jobs.snapshot();
    startup
}

fn install_notification_actions(app: &AppHandle, ctx: &Context) {
    let open = translate(ctx, "Open");
    let action_types = ["show-scan", "show-update", "show-audit"]
        .into_iter()
        .map(|action| {
            ActionType::builder(action)
                .actions(vec![Action::builder(action, open.clone()).build()])
                .build()
        })
        .collect();
    let _ = app.notification().register_action_types(action_types);
    let handle = app.clone();
    let _ = app.notification().on_action(move |performed| {
        let action = match performed.action_id() {
            "show-scan" | "show-update" | "show-audit" => Some(performed.action_id().to_owned()),
            "tap" => performed
                .notification()
                .and_then(|notification| notification.extra().get("clamui-action"))
                .and_then(Value::as_str)
                .filter(|action| matches!(*action, "show-scan" | "show-update" | "show-audit"))
                .map(ToOwned::to_owned),
            _ => None,
        };
        let Some(action) = action else {
            return;
        };
        let identity = performed
            .notification()
            .and_then(|notification| notification.extra().get("clamui-identity"))
            .cloned()
            .unwrap_or_else(|| json!({}));
        let _ = show_window(&handle);
        let _ = handle.emit(
            "clamui-event",
            json!({ "event": "notification-activated", "data": { "action": action, "identity": identity } }),
        );
    });
}

fn forwarded_instance_args(args: Vec<String>) -> Vec<String> {
    args.into_iter().skip(1).collect()
}

#[derive(Default)]
struct Targets {
    paths: Vec<String>,
    virustotal: bool,
}

fn parse_startup_targets(args: &[String], cwd: &Path) -> Result<Targets, String> {
    let mut targets = Targets::default();
    let mut positional_only = false;
    for argument in args {
        if !positional_only && argument == "--virustotal" {
            targets.virustotal = true;
            continue;
        }
        if !positional_only && argument == "--" {
            positional_only = true;
            continue;
        }
        if !positional_only && argument.starts_with('-') {
            continue;
        }
        targets
            .paths
            .push(path_to_wire(&decode_open_target(argument, cwd)?));
    }
    Ok(targets)
}

fn allow_navigation(url: &url::Url) -> bool {
    let production_origin =
        (url.scheme() == "tauri" && url.host_str() == Some("localhost") && url.port().is_none())
            || (url.scheme() == "http"
                && url.host_str() == Some("tauri.localhost")
                && matches!(url.port(), None | Some(80)));
    let development_origin = cfg!(debug_assertions)
        && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(1420);
    production_origin || development_origin
}

fn sync_profiles(ctx: &Context, tray: &TrayController) {
    let Ok(value) = dispatch(ctx, "profiles.list", json!({})) else {
        return;
    };
    let profiles = value
        .get("profiles")
        .and_then(Value::as_array)
        .cloned()
        .or_else(|| value.as_array().cloned())
        .unwrap_or_default();
    tray.update_profiles(profiles);
}

fn apply_start_minimize(app: &AppHandle) {
    let state = app.state::<AppState>();
    if state.tray.available() && state.start_minimized_pending.swap(false, Ordering::AcqRel) {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.hide();
        }
    }
}

fn show_window(app: &AppHandle) -> Result<(), String> {
    app.state::<AppState>()
        .start_minimized_pending
        .store(false, Ordering::Release);
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is unavailable".to_owned())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

fn toggle_window(app: &AppHandle) {
    app.state::<AppState>()
        .start_minimized_pending
        .store(false, Ordering::Release);
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(true) {
            let _ = window.hide();
        } else {
            let _ = show_window(app);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startup_arguments_keep_every_clamav_target() {
        let parsed =
            parse_startup_targets(&["/a".into(), "file:///b%20c".into()], Path::new("/")).unwrap();
        assert_eq!(parsed.paths, vec!["/a", "/b c"]);
        assert!(!parsed.virustotal);
    }

    #[test]
    fn virustotal_flag_is_separate_from_targets() {
        let parsed = parse_startup_targets(
            &["--virustotal".into(), "/a".into(), "/b".into()],
            Path::new("/"),
        )
        .unwrap();
        assert!(parsed.virustotal);
        assert_eq!(parsed.paths, vec!["/a", "/b"]);
    }

    #[test]
    fn startup_delimiter_preserves_flag_like_filenames() {
        let parsed = parse_startup_targets(
            &["--".into(), "--virustotal".into(), "--".into()],
            Path::new("/owned"),
        )
        .unwrap();
        assert!(!parsed.virustotal);
        assert_eq!(parsed.paths, vec!["/owned/--virustotal", "/owned/--"]);
    }

    #[test]
    fn non_utf8_file_uri_stays_lossless_at_the_frontend_boundary() {
        let parsed = parse_startup_targets(&["file:///tmp/%FF".into()], Path::new("/")).unwrap();
        assert_eq!(parsed.paths, vec!["file:///tmp/%FF"]);
    }

    #[test]
    fn concurrent_same_action_workers_remain_active_until_each_finishes() {
        let jobs = RunningJobs {
            entries: Mutex::new(HashMap::new()),
            next_token: AtomicU64::new(1),
            accepting: AtomicBool::new(true),
            idle: Condvar::new(),
        };
        let first = jobs.register("scanner.scan".into()).unwrap();
        let second = jobs.register("scanner.scan".into()).unwrap();
        drop(first);
        assert!(jobs.scan_active());
        assert_eq!(jobs.snapshot().len(), 1);
        drop(second);
        assert!(!jobs.scan_active());
    }
}
