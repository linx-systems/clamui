use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize)]
pub struct StartupState {
    pub paths: Vec<String>,
    pub virustotal: bool,
    pub tray_available: bool,
    pub version: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub active_jobs: Vec<String>,
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ChoosePathsOptions {
    pub title: Option<String>,
    pub multiple: Option<bool>,
    pub directory: Option<bool>,
    pub filters: Option<Vec<FileFilter>>,
}

#[derive(Debug, Deserialize)]
pub struct FileFilter {
    pub name: String,
    pub extensions: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct ChosenPaths {
    pub paths: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct SavedExport {
    pub saved: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct CloseResult {
    pub action: String,
}
