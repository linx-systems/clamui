use clamui_core::common::path_from_wire;
use std::path::{Path, PathBuf};
use url::Url;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloseAction {
    Prompt,
    Hide,
    Quit,
}

pub fn decode_open_target(raw: &str, cwd: &Path) -> Result<PathBuf, String> {
    let candidate = path_from_wire(raw)?;
    Ok(if candidate.is_absolute() {
        candidate
    } else {
        cwd.join(candidate)
    })
}

pub fn select_close_action(
    scan_active: bool,
    tray_available: bool,
    configured: Option<&str>,
    requested: Option<&str>,
) -> Result<CloseAction, String> {
    if scan_active && requested.is_none() {
        return Ok(CloseAction::Prompt);
    }
    let choice = requested.or(configured);
    match choice {
        Some("quit") => Ok(CloseAction::Quit),
        Some("minimize") if tray_available => Ok(CloseAction::Hide),
        Some("minimize") => Ok(CloseAction::Quit),
        Some("ask") | None if !tray_available => Ok(CloseAction::Quit),
        Some("ask") | None => Ok(CloseAction::Prompt),
        Some(_) => Err("invalid close choice".to_owned()),
    }
}

pub fn is_safe_external_url(input: &str) -> Result<Url, String> {
    let url = Url::parse(input).map_err(|_| "invalid URL".to_owned())?;
    match url.scheme() {
        "https" | "http" if url.host_str().is_some() => Ok(url),
        _ => Err("only absolute HTTP(S) URLs may be opened".to_owned()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_local_file_uris_without_losing_escaped_bytes() {
        let path = decode_open_target("file:///tmp/scan%20target", Path::new("/ignored")).unwrap();
        assert_eq!(path, Path::new("/tmp/scan target"));
    }

    #[test]
    fn refuses_non_local_file_uri_authorities() {
        assert!(decode_open_target("file://example.test/tmp/file", Path::new("/")).is_err());
    }

    #[test]
    fn external_opening_refuses_non_web_schemes() {
        assert!(is_safe_external_url("file:///etc/passwd").is_err());
        assert!(is_safe_external_url("javascript:alert(1)").is_err());
    }

    #[test]
    fn close_policy_prioritizes_an_active_scan_prompt() {
        assert_eq!(
            select_close_action(true, true, Some("quit"), None).unwrap(),
            CloseAction::Prompt
        );
    }

    #[test]
    fn minimize_requires_a_registered_tray_host() {
        assert_eq!(
            select_close_action(false, false, Some("minimize"), None).unwrap(),
            CloseAction::Quit
        );
    }

    #[test]
    fn default_close_quits_when_no_tray_host_exists() {
        assert_eq!(
            select_close_action(false, false, None, None).unwrap(),
            CloseAction::Quit
        );
    }
}
