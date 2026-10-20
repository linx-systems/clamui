//! Native CLI installation of the locally bundled privileged helper.

use super::{flatpak, HELPER_PATH, POLICY_PATH};
use crate::{AppResult, Context};
use std::ffi::{CStr, CString, OsStr, OsString};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const POLICY_BYTES: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../data/io.github.linx_systems.ClamUI.policy"
));
const HELPER_NAME: &str = "clamui-apply-preferences";
const DIRECTORY_MODE: u32 = 0o755;
static TEMPORARY_COUNTER: AtomicU64 = AtomicU64::new(0);

pub(super) fn install_cli_helper(ctx: &Context, prefix: &Path) -> AppResult<String> {
    let prefix_components = normalized_prefix_components(prefix)?;
    if prefix_components.is_empty() {
        if flatpak() {
            return Err(crate::i18n::translate(
                ctx,
                // Translators: keep "Flatpak" and "clamui-privileged-helper" unchanged.
                "ClamUI is running inside a Flatpak sandbox, which cannot install files on the host. Install the matching clamui-privileged-helper package on the host system instead.",
            ));
        }
        if unsafe { libc::geteuid() } != 0 {
            return Err(crate::i18n::translate(
                ctx,
                // Translators: keep the paths and "sudo clamui install-privileged-helper" command unchanged.
                "This command installs files under /usr and /usr/share and must be run as root. Try: sudo clamui install-privileged-helper",
            ));
        }
    }

    let executable = std::env::current_exe()
        .map_err(|error| format!("cannot locate the running ClamUI executable: {error}"))?;
    let source = executable
        .parent()
        .ok_or_else(|| {
            "cannot locate the directory containing the running ClamUI executable".to_owned()
        })?
        .join(HELPER_NAME);
    install_from_source(ctx, &prefix_components, &source)
}

fn install_from_source(
    ctx: &Context,
    prefix_components: &[OsString],
    source_path: &Path,
) -> AppResult<String> {
    let source = open_helper_source(source_path)?;
    let prefix = path_from_components(prefix_components);
    let result = (|| -> AppResult<()> {
        let prefix_directory =
            open_prefix_directory(prefix_components, prefix_components.is_empty())?;
        let usr_path = prefix.join("usr");
        let usr = ensure_directory(
            &prefix_directory,
            OsStr::new("usr"),
            &usr_path,
            prefix_components.is_empty(),
            !prefix_components.is_empty(),
        )?;
        let bin_path = usr_path.join("bin");
        let bin = ensure_directory(
            &usr,
            OsStr::new("bin"),
            &bin_path,
            prefix_components.is_empty(),
            !prefix_components.is_empty(),
        )?;
        let share_path = usr_path.join("share");
        let share = ensure_directory(
            &usr,
            OsStr::new("share"),
            &share_path,
            prefix_components.is_empty(),
            !prefix_components.is_empty(),
        )?;
        let polkit_path = share_path.join("polkit-1");
        let polkit = ensure_directory(
            &share,
            OsStr::new("polkit-1"),
            &polkit_path,
            prefix_components.is_empty(),
            !prefix_components.is_empty(),
        )?;
        let actions_path = polkit_path.join("actions");
        let actions = ensure_directory(
            &polkit,
            OsStr::new("actions"),
            &actions_path,
            prefix_components.is_empty(),
            !prefix_components.is_empty(),
        )?;

        atomic_install_from_file(
            &bin,
            OsStr::new(HELPER_NAME),
            &source,
            0o755,
            prefix_components.is_empty(),
        )?;
        atomic_install_bytes(
            &actions,
            OsStr::new("io.github.linx_systems.ClamUI.policy"),
            POLICY_BYTES,
            0o644,
            prefix_components.is_empty(),
        )
    })();
    result.map_err(|error| {
        crate::i18n::translate(
            ctx,
            // Translators: keep the {error} placeholder; it is a sanitized installation error.
            "Failed to install privileged helper: {error}",
        )
        .replace("{error}", &error)
    })?;

    let bin = prefix.join(HELPER_PATH.trim_start_matches('/'));
    let policy = prefix.join(POLICY_PATH.trim_start_matches('/'));
    Ok(crate::i18n::translate(
        ctx,
        // Translators: keep the {bin} and {policy} placeholders; they are installed file paths.
        "Installed privileged helper at {bin} and polkit policy at {policy}. Saving system ClamAV configuration from ClamUI should now work.",
    )
    .replace("{bin}", &bin.display().to_string())
    .replace("{policy}", &policy.display().to_string()))
}

fn normalized_prefix_components(prefix: &Path) -> AppResult<Vec<OsString>> {
    if !prefix.is_absolute() {
        return Err(format!(
            "installation prefix must be an absolute path: {}",
            prefix.display()
        ));
    }

    let mut components = Vec::new();
    for component in prefix.components() {
        match component {
            Component::RootDir | Component::CurDir => {}
            Component::Normal(component) => components.push(component.to_os_string()),
            Component::ParentDir => {
                components.pop();
            }
            Component::Prefix(_) => {
                return Err(format!(
                    "installation prefix has an unsupported path prefix: {}",
                    prefix.display()
                ));
            }
        }
    }
    Ok(components)
}

fn path_from_components(components: &[OsString]) -> PathBuf {
    let mut path = PathBuf::from("/");
    for component in components {
        path.push(component);
    }
    path
}

fn open_helper_source(path: &Path) -> AppResult<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                format!("Required source file not found: {}", path.display())
            } else {
                format!(
                    "cannot safely open required helper source {}: {error}",
                    path.display()
                )
            }
        })?;
    let metadata = file.metadata().map_err(|error| {
        format!(
            "cannot inspect required helper source {}: {error}",
            path.display()
        )
    })?;
    if !metadata.is_file() {
        return Err(format!(
            "required helper source is not a regular file: {}",
            path.display()
        ));
    }
    if metadata.mode() & 0o111 == 0 {
        return Err(format!(
            "required helper source is not executable: {}",
            path.display()
        ));
    }
    let mut magic = [0_u8; 4];
    let read = unsafe { libc::pread(file.as_raw_fd(), magic.as_mut_ptr().cast(), magic.len(), 0) };
    if read != magic.len() as isize || magic != [0x7f, b'E', b'L', b'F'] {
        return Err(format!(
            "required helper source is not a native executable: {}",
            path.display()
        ));
    }
    Ok(file)
}

fn open_prefix_directory(components: &[OsString], system_install: bool) -> AppResult<File> {
    let root = open_directory(Path::new("/"))?;
    if system_install {
        validate_directory(&root, Path::new("/"), true, false)?;
    } else {
        validate_staging_ancestor(&root, Path::new("/"))?;
    }
    let mut directory = root;
    let mut path = PathBuf::from("/");
    for (index, component) in components.iter().enumerate() {
        if !system_install {
            validate_staging_ancestor(&directory, &path)?;
        }
        path.push(component);
        directory = ensure_directory(
            &directory,
            component,
            &path,
            system_install,
            !system_install && index + 1 == components.len(),
        )?;
    }
    Ok(directory)
}

fn open_directory(path: &Path) -> AppResult<File> {
    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| format!("cannot safely open directory {}: {error}", path.display()))
}

fn ensure_directory(
    parent: &File,
    name: &OsStr,
    label: &Path,
    system_install: bool,
    private_staging: bool,
) -> AppResult<File> {
    let name = c_name(name)?;
    match open_directory_at(parent, &name) {
        Ok(directory) => {
            validate_directory(&directory, label, system_install, private_staging)?;
            Ok(directory)
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            create_directory_at(parent, &name)?;
            let directory = open_directory_at(parent, &name).map_err(|error| {
                format!(
                    "cannot safely open newly created directory {}: {error}",
                    label.display()
                )
            })?;
            directory
                .set_permissions(fs::Permissions::from_mode(DIRECTORY_MODE))
                .map_err(|error| {
                    format!(
                        "cannot set directory permissions {}: {error}",
                        label.display()
                    )
                })?;
            validate_directory(&directory, label, system_install, private_staging)?;
            Ok(directory)
        }
        Err(error) => Err(format!(
            "cannot safely open destination directory {}: {error}",
            label.display()
        )),
    }
}

// Same-UID processes can already modify a caller-owned staging tree; this
// boundary excludes other users from renaming an opened directory out of it.
fn validate_staging_ancestor(directory: &File, label: &Path) -> AppResult<()> {
    let metadata = directory
        .metadata()
        .map_err(|error| format!("cannot inspect directory {}: {error}", label.display()))?;
    let owner = metadata.uid();
    let caller = unsafe { libc::geteuid() };
    if (owner != 0 && owner != caller)
        || (metadata.mode() & 0o022 != 0 && metadata.mode() & 0o1000 == 0)
    {
        return Err(format!(
            "Refusing to install through an unsafe staging parent directory: {}",
            label.display()
        ));
    }
    Ok(())
}

fn validate_directory(
    directory: &File,
    label: &Path,
    system_install: bool,
    private_staging: bool,
) -> AppResult<()> {
    let metadata = directory
        .metadata()
        .map_err(|error| format!("cannot inspect directory {}: {error}", label.display()))?;
    if !metadata.is_dir() {
        return Err(format!(
            "destination is not a directory: {}",
            label.display()
        ));
    }
    if system_install && (metadata.uid() != 0 || metadata.mode() & 0o022 != 0) {
        return Err(format!(
            "Refusing to install into an unsafe directory: {}",
            label.display()
        ));
    }
    if private_staging
        && (metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o022 != 0)
    {
        return Err(format!(
            "Refusing to install into an unsafe staging directory: {}",
            label.display()
        ));
    }
    Ok(())
}

fn c_name(name: &OsStr) -> AppResult<CString> {
    CString::new(name.as_bytes()).map_err(|_| "path contains a NUL byte".to_owned())
}

fn open_directory_at(parent: &File, name: &CStr) -> io::Result<File> {
    let descriptor = unsafe {
        libc::openat(
            parent.as_raw_fd(),
            name.as_ptr(),
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        )
    };
    if descriptor < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(unsafe { File::from_raw_fd(descriptor) })
    }
}

fn create_directory_at(parent: &File, name: &CStr) -> AppResult<()> {
    let result = unsafe {
        libc::mkdirat(
            parent.as_raw_fd(),
            name.as_ptr(),
            DIRECTORY_MODE as libc::mode_t,
        )
    };
    if result == 0 || io::Error::last_os_error().kind() == io::ErrorKind::AlreadyExists {
        Ok(())
    } else {
        Err(format!(
            "cannot create destination directory: {}",
            io::Error::last_os_error()
        ))
    }
}

fn atomic_install_from_file(
    directory: &File,
    destination: &OsStr,
    source: &File,
    mode: u32,
    system_install: bool,
) -> AppResult<()> {
    let mut source = source
        .try_clone()
        .map_err(|error| format!("cannot duplicate helper source descriptor: {error}"))?;
    let mut temporary = create_temporary_file(directory, destination, mode, system_install)?;
    let result = (|| -> AppResult<()> {
        io::copy(&mut source, &mut temporary.file)
            .map_err(|error| format!("cannot copy helper source: {error}"))?;
        temporary
            .file
            .sync_all()
            .map_err(|error| format!("cannot sync helper file: {error}"))?;
        replace_file_at(directory, &temporary.name, destination)?;
        directory
            .sync_all()
            .map_err(|error| format!("cannot sync helper directory: {error}"))
    })();
    if result.is_err() {
        let _ = unlink_at(directory, &temporary.name);
    }
    result
}

fn atomic_install_bytes(
    directory: &File,
    destination: &OsStr,
    bytes: &[u8],
    mode: u32,
    system_install: bool,
) -> AppResult<()> {
    let mut temporary = create_temporary_file(directory, destination, mode, system_install)?;
    let result = (|| -> AppResult<()> {
        temporary
            .file
            .write_all(bytes)
            .map_err(|error| format!("cannot write policy file: {error}"))?;
        temporary
            .file
            .sync_all()
            .map_err(|error| format!("cannot sync policy file: {error}"))?;
        replace_file_at(directory, &temporary.name, destination)?;
        directory
            .sync_all()
            .map_err(|error| format!("cannot sync policy directory: {error}"))
    })();
    if result.is_err() {
        let _ = unlink_at(directory, &temporary.name);
    }
    result
}

struct TemporaryFile {
    name: CString,
    file: File,
}

fn create_temporary_file(
    directory: &File,
    destination: &OsStr,
    mode: u32,
    system_install: bool,
) -> AppResult<TemporaryFile> {
    let destination = destination
        .to_str()
        .ok_or_else(|| "destination file name is not UTF-8".to_owned())?;
    for _ in 0..32 {
        let sequence = TEMPORARY_COUNTER.fetch_add(1, Ordering::Relaxed);
        let name = CString::new(format!(
            ".{destination}.{}-{sequence}.tmp",
            std::process::id()
        ))
        .expect("generated temporary file names contain no NUL");
        let descriptor = unsafe {
            libc::openat(
                directory.as_raw_fd(),
                name.as_ptr(),
                libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_CLOEXEC | libc::O_NOFOLLOW,
                mode as libc::mode_t,
            )
        };
        if descriptor >= 0 {
            let file = unsafe { File::from_raw_fd(descriptor) };
            if let Err(error) = file.set_permissions(fs::Permissions::from_mode(mode)) {
                let _ = unlink_at(directory, &name);
                return Err(format!("cannot set temporary file permissions: {error}"));
            }
            if system_install {
                let metadata = match file.metadata() {
                    Ok(metadata) => metadata,
                    Err(error) => {
                        let _ = unlink_at(directory, &name);
                        return Err(format!(
                            "cannot inspect temporary installation file: {error}"
                        ));
                    }
                };
                if metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
                    let _ = unlink_at(directory, &name);
                    return Err(
                        "temporary installation file is not root-owned and immutable".to_owned(),
                    );
                }
            }
            return Ok(TemporaryFile { name, file });
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::AlreadyExists {
            return Err(format!(
                "cannot create temporary installation file: {error}"
            ));
        }
    }
    Err("cannot allocate a temporary installation file".to_owned())
}

fn replace_file_at(directory: &File, temporary: &CStr, destination: &OsStr) -> AppResult<()> {
    let destination = c_name(destination)?;
    let result = unsafe {
        libc::renameat(
            directory.as_raw_fd(),
            temporary.as_ptr(),
            directory.as_raw_fd(),
            destination.as_ptr(),
        )
    };
    if result == 0 {
        Ok(())
    } else {
        Err(format!(
            "cannot atomically replace destination file: {}",
            io::Error::last_os_error()
        ))
    }
}

fn unlink_at(directory: &File, name: &CStr) -> io::Result<()> {
    let result = unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), 0) };
    if result == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(test)]
fn install_test_source(ctx: &Context, prefix: &Path, source: &Path) -> AppResult<String> {
    let prefix_components = normalized_prefix_components(prefix)?;
    install_from_source(ctx, &prefix_components, source)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::common::Paths;
    use std::fs;
    use std::os::unix::fs::{symlink, MetadataExt, PermissionsExt};
    use std::path::{Path, PathBuf};
    fn context(root: &Path) -> Context {
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))
            .expect("make test root private");
        Context::with_paths(Paths {
            home: root.join("home"),
            config_dir: root.join("config"),
            data_dir: root.join("data"),
        })
        .expect("create test context")
    }

    fn source(root: &Path) -> PathBuf {
        let source = root.join("clamui-apply-preferences");
        fs::write(&source, b"\x7fELF clamui native helper test payload")
            .expect("write test helper source");
        fs::set_permissions(&source, fs::Permissions::from_mode(0o755))
            .expect("mark test helper executable");
        source
    }

    #[test]
    fn normalized_root_spellings_are_system_prefixes() {
        assert!(normalized_prefix_components(Path::new("/usr/.."))
            .expect("normalize root spelling")
            .is_empty());
        assert!(normalized_prefix_components(Path::new("/./"))
            .expect("normalize root spelling")
            .is_empty());
    }

    #[test]
    fn stages_helper_and_policy_with_runtime_modes() {
        let root = tempfile::tempdir().expect("create test root");
        let source = source(root.path());
        let prefix = root.path().join("stage");

        let detail = install_test_source(&context(root.path()), &prefix, &source)
            .expect("stage helper and policy");
        let helper = prefix.join("usr/bin/clamui-apply-preferences");
        let policy = prefix.join("usr/share/polkit-1/actions/io.github.linx_systems.ClamUI.policy");

        assert_eq!(
            fs::read(&helper).expect("read staged helper"),
            fs::read(&source).expect("read source helper")
        );
        assert_eq!(
            fs::metadata(&helper).expect("inspect helper").mode() & 0o777,
            0o755
        );
        assert_eq!(
            fs::metadata(&policy).expect("inspect policy").mode() & 0o777,
            0o644
        );
        assert!(String::from_utf8(fs::read(&policy).expect("read policy"))
            .expect("policy is UTF-8")
            .contains("io.github.linx_systems.clamui.apply-preferences"));
        assert!(detail.contains("clamui-apply-preferences"));
    }

    #[test]
    fn missing_source_fails_before_creating_staging_prefix() {
        let root = tempfile::tempdir().expect("create test root");
        let prefix = root.path().join("stage");

        let result = install_test_source(
            &context(root.path()),
            &prefix,
            &root.path().join("missing-helper"),
        );

        assert!(matches!(result, Err(error) if error.contains("Required source file not found")));
        assert!(!prefix.exists());
    }
    #[test]
    fn mutable_staging_prefix_is_rejected_before_external_sentinel_can_change() {
        let root = tempfile::tempdir().expect("create test root");
        let source = source(root.path());
        let prefix = root.path().join("stage");
        let external = root.path().join("external");
        fs::create_dir_all(external.join("bin")).expect("create external directory");
        let sentinel = external.join("bin/clamui-apply-preferences");
        fs::write(&sentinel, b"external sentinel").expect("write external sentinel");
        fs::create_dir_all(&prefix).expect("create mutable staging prefix");
        fs::set_permissions(&prefix, fs::Permissions::from_mode(0o777))
            .expect("make staging prefix mutable");
        symlink(&external, prefix.join("usr")).expect("create hostile child symlink");

        let result = install_test_source(&context(root.path()), &prefix, &source);

        assert!(result.is_err());
        assert_eq!(
            fs::read(&sentinel).expect("read external sentinel"),
            b"external sentinel"
        );
    }

    #[test]
    fn symlinked_destination_directory_cannot_touch_external_sentinel() {
        let root = tempfile::tempdir().expect("create test root");
        let source = source(root.path());
        let prefix = root.path().join("stage");
        let external = root.path().join("external");
        fs::create_dir_all(external.join("bin")).expect("create external directory");
        let sentinel = external.join("bin/clamui-apply-preferences");
        fs::write(&sentinel, b"external sentinel").expect("write external sentinel");
        fs::create_dir_all(&prefix).expect("create staging prefix");
        fs::set_permissions(&prefix, fs::Permissions::from_mode(0o755))
            .expect("make staging prefix trusted");
        symlink(&external, prefix.join("usr")).expect("create hostile directory symlink");

        let result = install_test_source(&context(root.path()), &prefix, &source);

        assert!(result.is_err());
        assert_eq!(
            fs::read(&sentinel).expect("read external sentinel"),
            b"external sentinel"
        );
    }

    #[test]
    fn destination_symlink_is_replaced_without_touching_external_sentinel() {
        let root = tempfile::tempdir().expect("create test root");
        let source = source(root.path());
        let prefix = root.path().join("stage");
        let usr = prefix.join("usr");
        let bin = usr.join("bin");
        fs::create_dir_all(&bin).expect("create binary directory");
        for directory in [&prefix, &usr, &bin] {
            fs::set_permissions(directory, fs::Permissions::from_mode(0o755))
                .expect("make test directory trusted");
        }
        let sentinel = root.path().join("external-sentinel");
        fs::write(&sentinel, b"external sentinel").expect("write external sentinel");
        symlink(&sentinel, bin.join("clamui-apply-preferences"))
            .expect("create hostile destination symlink");

        install_test_source(&context(root.path()), &prefix, &source)
            .expect("replace destination symlink safely");

        let helper = bin.join("clamui-apply-preferences");
        assert!(!fs::symlink_metadata(&helper)
            .expect("inspect staged helper")
            .file_type()
            .is_symlink());
        assert_eq!(
            fs::read(&helper).expect("read staged helper"),
            fs::read(&source).expect("read source helper")
        );
        assert_eq!(
            fs::read(&sentinel).expect("read external sentinel"),
            b"external sentinel"
        );
    }
}
