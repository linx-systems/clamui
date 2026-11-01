use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use clamui_core::platform::{
    device_job_id, install_integration_at, integration_status_at, remove_integration_at,
    DeviceScanPolicy, DeviceType, IntegrationPaths, MountInfo,
};

fn temporary_share(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before unix epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "clamui-platform-{name}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create temporary integration root");
    root
}

fn paths(root: PathBuf, kde_session_version: Option<&str>) -> IntegrationPaths {
    IntegrationPaths {
        local_share: root,
        flatpak: true,
        kde_session_version: kde_session_version.map(str::to_owned),
    }
}

fn status(paths: &IntegrationPaths, manager: &str) -> String {
    integration_status_at(paths, manager)
        .expect("inspect integration")
        .get("status")
        .and_then(serde_json::Value::as_str)
        .expect("status string")
        .to_owned()
}

#[test]
fn device_policy_filters_type_size_unknown_size_and_battery() {
    let removable = MountInfo {
        mount_point: "/media/usb".to_owned(),
        device_name: "USB".to_owned(),
        device_type: DeviceType::Removable,
        volume_uuid: "usb-1".to_owned(),
        size_bytes: 0,
    };
    let policy = DeviceScanPolicy {
        enabled: true,
        allowed_types: vec![DeviceType::Removable, DeviceType::External],
        max_size_gb: 32,
        skip_on_battery: true,
        on_battery: false,
    };
    assert!(policy.permits(&removable), "unknown size must fail open");

    let too_large = MountInfo {
        size_bytes: 33 * 1024 * 1024 * 1024,
        ..removable.clone()
    };
    assert!(!policy.permits(&too_large));
    assert!(!DeviceScanPolicy {
        on_battery: true,
        ..policy.clone()
    }
    .permits(&removable));
    assert!(!DeviceScanPolicy {
        allowed_types: vec![DeviceType::External],
        ..policy
    }
    .permits(&removable));
}

#[test]
fn nemo_install_repair_and_remove_are_stateful_and_idempotent() {
    let root = temporary_share("nemo");
    let paths = paths(root.clone(), None);
    assert_eq!(status(&paths, "nemo"), "not_installed");

    install_integration_at(&paths, "nemo", false).expect("install nemo integration");
    assert_eq!(status(&paths, "nemo"), "installed");
    assert!(root
        .join("nemo/actions/io.github.linx_systems.ClamUI.nemo_action")
        .is_file());

    fs::remove_file(root.join("nemo/actions/io.github.linx_systems.ClamUI-virustotal.nemo_action"))
        .expect("make partial installation");
    assert_eq!(status(&paths, "nemo"), "partial");
    install_integration_at(&paths, "nemo", true).expect("repair only missing nemo asset");
    assert_eq!(status(&paths, "nemo"), "installed");

    remove_integration_at(&paths, "nemo").expect("remove nemo integration");
    remove_integration_at(&paths, "nemo").expect("idempotent remove");
    assert_eq!(status(&paths, "nemo"), "not_installed");
    fs::remove_dir_all(root).expect("remove temporary integration root");
}

#[test]
fn dolphin_repair_migrates_stale_legacy_service_menu() {
    let root = temporary_share("dolphin");
    let legacy = paths(root.clone(), Some("5"));
    install_integration_at(&legacy, "dolphin", false).expect("install legacy dolphin menu");

    let modern = paths(root.clone(), Some("6"));
    assert_eq!(status(&modern, "dolphin"), "partial");
    install_integration_at(&modern, "dolphin", true).expect("repair dolphin into modern directory");
    assert_eq!(status(&modern, "dolphin"), "installed");
    assert!(root
        .join("kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop")
        .is_file());
    assert!(!root
        .join("kservices5/ServiceMenus/io.github.linx_systems.ClamUI.service.desktop")
        .exists());
    fs::remove_dir_all(root).expect("remove temporary integration root");
}

#[cfg(unix)]
#[test]
fn installation_rejects_a_symlinked_destination_parent() {
    use std::os::unix::fs::symlink;

    let root = temporary_share("symlink");
    let outside = temporary_share("outside");
    symlink(&outside, root.join("nemo")).expect("create unsafe destination symlink");
    let paths = paths(root.clone(), None);
    let error =
        install_integration_at(&paths, "nemo", false).expect_err("reject symlink destination");
    assert!(error.contains("symlink"));
    fs::remove_dir_all(root).expect("remove temporary integration root");
    assert!(
        !outside.join("actions").exists(),
        "validation must reject the symlink before creating directories through it"
    );
    fs::remove_dir_all(outside).expect("remove temporary external root");
}

#[test]
fn cloned_volume_uuids_receive_distinct_mount_generation_jobs() {
    let first = MountInfo {
        mount_point: "/media/first".to_owned(),
        device_name: "first".to_owned(),
        device_type: DeviceType::Removable,
        volume_uuid: "cloned-filesystem".to_owned(),
        size_bytes: 0,
    };
    let second = MountInfo {
        mount_point: "/media/second".to_owned(),
        ..first.clone()
    };
    assert_ne!(device_job_id(&first, 7), device_job_id(&second, 8));
    assert_ne!(device_job_id(&first, 7), device_job_id(&second, 7));
}

#[cfg(unix)]
#[test]
fn removal_rejects_symlinked_managed_parent_without_touching_target() {
    use std::os::unix::fs::symlink;

    let root = temporary_share("remove-symlink");
    let outside = temporary_share("remove-outside");
    let actions = outside.join("actions");
    fs::create_dir_all(&actions).expect("create external actions");
    let protected = actions.join("io.github.linx_systems.ClamUI.nemo_action");
    fs::write(&protected, b"external integration").expect("create protected external file");
    symlink(&outside, root.join("nemo")).expect("create unsafe managed parent");

    let paths = paths(root.clone(), None);
    assert!(remove_integration_at(&paths, "nemo").is_err());
    assert_eq!(
        fs::read(&protected).expect("external file remains"),
        b"external integration"
    );

    fs::remove_dir_all(root).expect("remove temporary integration root");
    fs::remove_dir_all(outside).expect("remove temporary external root");
}
