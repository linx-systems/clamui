use clamui_core::common::without_snap_entries;
use std::path::Path;

#[test]
fn host_commands_drop_only_the_snap_data_directories() {
    let root = Path::new("/snap/clamui/42");
    assert_eq!(
        without_snap_entries(
            "/snap/clamui/42/usr/share:/usr/local/share:/usr/share:/snap/clamui-other/usr/share",
            root
        ),
        "/usr/local/share:/usr/share:/snap/clamui-other/usr/share"
    );
    assert_eq!(without_snap_entries("/snap/clamui/42/usr/share", root), "");
    assert_eq!(without_snap_entries("::/usr/share:", root), "/usr/share");
}
