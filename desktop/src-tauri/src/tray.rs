use clamui_core::common::{expand_path, is_flatpak, path_to_wire};
use ksni::{
    menu::{StandardItem, SubMenu},
    MenuItem, Status, Tray, TrayMethods,
};
use serde_json::{json, Value};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Sender},
        Arc, Mutex,
    },
    thread,
};

pub type TrayEvent = Arc<dyn Fn(&str, Value) + Send + Sync>;

#[derive(Clone)]
pub struct TrayLabels {
    pub show: String,
    pub quick_scan: String,
    pub full_scan: String,
    pub home_folder: String,
    pub update_database: String,
    pub scan_profile: String,
    pub quit: String,
}

pub struct TrayController {
    available: Arc<AtomicBool>,
    worker: Mutex<Option<TrayWorker>>,
    profiles: Mutex<Vec<Value>>,
    status: Mutex<TrayStatus>,
}

struct TrayWorker {
    sender: Sender<TrayUpdate>,
    join: thread::JoinHandle<()>,
}

enum TrayUpdate {
    Start(ksni::Handle<NativeTray>),
    Profiles(Vec<Value>),
    Status(TrayStatus),
    Shutdown,
}

impl TrayController {
    pub fn start(
        emit: TrayEvent,
        labels: TrayLabels,
        quick_scan_fallback: String,
        protected_icon: &tauri::image::Image<'_>,
    ) -> Arc<Self> {
        let available = Arc::new(AtomicBool::new(false));
        let tray = NativeTray {
            emit,
            available: available.clone(),
            labels,
            status: TrayStatus::Protected,
            profiles: Vec::new(),
            quick_scan_fallback,
            protected_icon: sni_icon(protected_icon),
        };
        let controller = Arc::new(Self {
            available,
            worker: Mutex::new(None),
            profiles: Mutex::new(Vec::new()),
            status: Mutex::new(TrayStatus::Protected),
        });
        let (sender, receiver) = mpsc::channel();
        let Ok(join) = thread::Builder::new()
            .name("clamui-tray-updates".into())
            .spawn(move || {
                let Ok(TrayUpdate::Start(handle)) = receiver.recv() else {
                    return;
                };
                while let Ok(update) = receiver.recv() {
                    match update {
                        TrayUpdate::Profiles(profiles) => {
                            if tauri::async_runtime::block_on(
                                handle.update(move |tray| tray.profiles = profiles),
                            )
                            .is_none()
                            {
                                break;
                            }
                        }
                        TrayUpdate::Status(status) => {
                            if tauri::async_runtime::block_on(
                                handle.update(move |tray| tray.status = status),
                            )
                            .is_none()
                            {
                                break;
                            }
                        }
                        TrayUpdate::Shutdown => break,
                        TrayUpdate::Start(_) => {}
                    }
                }
                tauri::async_runtime::block_on(handle.shutdown());
            })
        else {
            return controller;
        };
        let tray_service = if is_flatpak() {
            tray.disable_dbus_name(true)
        } else {
            tray.assume_sni_available(false)
        };
        let Ok(handle) = tauri::async_runtime::block_on(tray_service.spawn()) else {
            drop(sender);
            match join.join() {
                Ok(()) | Err(_) => {}
            }
            return controller;
        };
        if let Err(error) = sender.send(TrayUpdate::Start(handle)) {
            if let TrayUpdate::Start(handle) = error.0 {
                tauri::async_runtime::block_on(handle.shutdown());
            }
            match join.join() {
                Ok(()) | Err(_) => {}
            }
            return controller;
        }
        // The async spawn completes only after SNI registration and host
        // readiness checks; service creation alone is not tray readiness.
        controller.available.store(true, Ordering::Release);
        *controller.worker.lock().expect("tray worker poisoned") =
            Some(TrayWorker { sender, join });
        controller
    }

    pub fn available(&self) -> bool {
        self.available.load(Ordering::Acquire)
    }

    pub fn update_profiles(&self, profiles: Vec<Value>) {
        let mut current = self.profiles.lock().expect("tray profiles poisoned");
        if *current == profiles {
            return;
        }
        *current = profiles.clone();
        drop(current);
        self.send(TrayUpdate::Profiles(profiles));
    }

    pub fn apply_event(&self, event: &str, data: &Value) {
        let status = match event {
            "scan-progress" => Some(TrayStatus::Scanning),
            "scan-complete" => match data
                .get("result")
                .and_then(|result| result.get("status"))
                .and_then(Value::as_str)
            {
                Some("infected") => Some(TrayStatus::Threat),
                Some("clean") => Some(TrayStatus::Protected),
                Some("cancelled") | Some("error") | None => Some(TrayStatus::Warning),
                Some(_) => Some(TrayStatus::Warning),
            },
            "update-complete" => {
                let result = data.get("result").unwrap_or(data);
                match (
                    result.get("status").and_then(Value::as_str),
                    result.get("update_method").and_then(Value::as_str),
                ) {
                    (Some("success") | Some("up_to_date"), Some("service_signal")) => {
                        Some(TrayStatus::Warning)
                    }
                    (Some("success") | Some("up_to_date"), _) => Some(TrayStatus::Protected),
                    (Some("error") | Some("cancelled") | None, _) => Some(TrayStatus::Warning),
                    _ => Some(TrayStatus::Warning),
                }
            }
            _ => None,
        };
        if let Some(status) = status {
            let mut current = self.status.lock().expect("tray status poisoned");
            if *current == status {
                return;
            }
            *current = status;
            drop(current);
            self.send(TrayUpdate::Status(status));
        }
    }

    fn send(&self, update: TrayUpdate) {
        if let Some(worker) = self.worker.lock().expect("tray worker poisoned").as_ref() {
            if worker.sender.send(update).is_err() {
                self.available.store(false, Ordering::Release);
            }
        }
    }

    pub fn shutdown(&self) {
        self.available.store(false, Ordering::Release);
        if let Some(worker) = self.worker.lock().expect("tray worker poisoned").take() {
            if worker.sender.send(TrayUpdate::Shutdown).is_err() {
                self.available.store(false, Ordering::Release);
            }
            match worker.join.join() {
                Ok(()) | Err(_) => {}
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum TrayStatus {
    Protected,
    Warning,
    Scanning,
    Threat,
}

struct NativeTray {
    emit: TrayEvent,
    available: Arc<AtomicBool>,
    labels: TrayLabels,
    status: TrayStatus,
    profiles: Vec<Value>,
    quick_scan_fallback: String,
    protected_icon: ksni::Icon,
}

impl NativeTray {
    fn item(
        label: &str,
        icon_name: &str,
        emit: TrayEvent,
        event: &'static str,
        data: Value,
    ) -> MenuItem<Self> {
        StandardItem {
            label: label.into(),
            icon_name: icon_name.into(),
            activate: Box::new(move |_| emit(event, data.clone())),
            ..Default::default()
        }
        .into()
    }

    fn quick_scan_event(&self) -> Value {
        let quick_profile = self
            .profiles
            .iter()
            .find(|profile| profile.get("name").and_then(Value::as_str) == Some("Quick Scan"));
        let targets = quick_profile
            .and_then(|profile| profile.get("targets"))
            .and_then(Value::as_array)
            .map(|targets| {
                targets
                    .iter()
                    .filter_map(Value::as_str)
                    .map(expand_path)
                    .map(|path| path_to_wire(&path))
                    .collect::<Vec<_>>()
            })
            .filter(|targets| !targets.is_empty())
            .unwrap_or_else(|| vec![self.quick_scan_fallback.clone()]);
        let mut event = json!({ "paths": targets, "start": true, "virustotal": false });
        if let Some(id) = quick_profile
            .and_then(|profile| profile.get("id"))
            .and_then(Value::as_str)
        {
            event["profile_id"] = Value::String(id.to_owned());
        }
        event
    }
}

fn sni_icon(image: &tauri::image::Image<'_>) -> ksni::Icon {
    let rgba = image.rgba();
    let mut data = Vec::with_capacity(rgba.len());
    for pixel in rgba.chunks_exact(4) {
        data.extend_from_slice(&[pixel[3], pixel[0], pixel[1], pixel[2]]);
    }
    debug_assert!(rgba.chunks_exact(4).remainder().is_empty());
    ksni::Icon {
        width: i32::try_from(image.width()).expect("bundled tray icon width exceeds SNI limits"),
        height: i32::try_from(image.height()).expect("bundled tray icon height exceeds SNI limits"),
        data,
    }
}

impl Tray for NativeTray {
    fn id(&self) -> String {
        "clamui".into()
    }

    fn title(&self) -> String {
        "ClamUI".into()
    }

    fn status(&self) -> Status {
        match self.status {
            TrayStatus::Protected | TrayStatus::Scanning => Status::Active,
            TrayStatus::Warning | TrayStatus::Threat => Status::NeedsAttention,
        }
    }

    fn icon_name(&self) -> String {
        match self.status {
            TrayStatus::Protected => String::new(),
            TrayStatus::Warning => "dialog-warning".into(),
            TrayStatus::Scanning => "view-refresh".into(),
            TrayStatus::Threat => "dialog-error".into(),
        }
    }

    fn icon_pixmap(&self) -> Vec<ksni::Icon> {
        match self.status {
            TrayStatus::Protected => vec![self.protected_icon.clone()],
            TrayStatus::Warning | TrayStatus::Scanning | TrayStatus::Threat => Vec::new(),
        }
    }

    fn attention_icon_name(&self) -> String {
        "dialog-warning".into()
    }

    fn activate(&mut self, _x: i32, _y: i32) {
        (self.emit)("toggle-window", json!({}));
    }

    fn menu(&self) -> Vec<MenuItem<Self>> {
        let mut profile_items = Vec::new();
        for profile in &self.profiles {
            if let (Some(id), Some(name)) = (
                profile.get("id").and_then(Value::as_str),
                profile.get("name").and_then(Value::as_str),
            ) {
                let label: &str =
                    if profile.get("is_default").and_then(Value::as_bool) == Some(true) {
                        match name {
                            "Quick Scan" => &self.labels.quick_scan,
                            "Full Scan" => &self.labels.full_scan,
                            "Home Folder" => &self.labels.home_folder,
                            _ => name,
                        }
                    } else {
                        name
                    };
                profile_items.push(Self::item(
                    label,
                    "document-properties",
                    self.emit.clone(),
                    "select-profile",
                    json!({ "profile_id": id }),
                ));
            }
        }
        let quick_scan = self.quick_scan_event();
        let mut menu = vec![
            Self::item(
                &self.labels.show,
                "security-high",
                self.emit.clone(),
                "toggle-window",
                json!({}),
            ),
            Self::item(
                &self.labels.quick_scan,
                "system-search",
                self.emit.clone(),
                "open-targets",
                quick_scan,
            ),
            Self::item(
                &self.labels.full_scan,
                "drive-harddisk",
                self.emit.clone(),
                "open-targets",
                json!({ "paths": ["/"], "start": true }),
            ),
            Self::item(
                &self.labels.update_database,
                "software-update-available",
                self.emit.clone(),
                "start-update",
                json!({}),
            ),
        ];
        if !profile_items.is_empty() {
            menu.push(
                SubMenu {
                    label: self.labels.scan_profile.clone(),
                    submenu: profile_items,
                    ..Default::default()
                }
                .into(),
            );
        }
        menu.push(MenuItem::Separator);
        menu.push(Self::item(
            &self.labels.quit,
            "application-exit",
            self.emit.clone(),
            "quit",
            json!({}),
        ));
        menu
    }

    fn watcher_online(&self) {
        self.available.store(true, Ordering::Release);
        (self.emit)("tray-availability", json!({ "available": true }));
    }

    fn watcher_offline(&self, _reason: ksni::OfflineReason) -> bool {
        self.available.store(false, Ordering::Release);
        (self.emit)("tray-availability", json!({ "available": false }));
        true
    }
}

#[cfg(test)]
mod tests {
    use super::sni_icon;

    #[test]
    fn sni_icon_encodes_rgba_as_network_order_argb() {
        let image = tauri::image::Image::new(
            &[
                0x12, 0x34, 0x56, 0x78, // red, green, blue, alpha
                0x9a, 0xbc, 0xde, 0xf0,
            ],
            2,
            1,
        );

        let icon = sni_icon(&image);

        assert_eq!((icon.width, icon.height), (2, 1));
        assert_eq!(
            icon.data,
            vec![0x78, 0x12, 0x34, 0x56, 0xf0, 0x9a, 0xbc, 0xde]
        );
    }
}
