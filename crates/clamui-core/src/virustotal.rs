use crate::credentials::{Account, CredentialStore};
use crate::{common::path_from_wire, AppResult, Context};
use reqwest::blocking::{multipart, Client};
use reqwest::header::HeaderValue;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const VT_API_BASE: &str = "https://www.virustotal.com/api/v3";
pub const VT_MAX_FILE_SIZE: u64 = 650 * 1024 * 1024;
pub const VT_DIRECT_UPLOAD_MAX: u64 = 32 * 1024 * 1024;
pub const VT_RATE_LIMIT_REQUESTS: usize = 4;
pub const VT_RATE_LIMIT_WINDOW: Duration = Duration::from_secs(60);
pub const VT_DAILY_RATE_LIMIT_REQUESTS: usize = 500;
pub const VT_DAILY_RATE_LIMIT_WINDOW: Duration = Duration::from_secs(24 * 60 * 60);
pub const VT_REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
pub const VT_UPLOAD_TIMEOUT: Duration = Duration::from_secs(300);
pub const VT_MAX_RETRIES: usize = 3;
const VT_RETRY_BASE_DELAY: Duration = Duration::from_secs(2);
const ANALYSIS_POLL_INTERVAL: Duration = Duration::from_secs(5);
const ANALYSIS_MAX_WAIT: Duration = Duration::from_secs(120);

struct RateLimiter {
    history: Mutex<RateLimitHistory>,
}

#[derive(Default)]
struct RateLimitHistory {
    minute_requests: Vec<Instant>,
    daily_requests: Vec<Instant>,
}

impl RateLimiter {
    fn new() -> Self {
        Self {
            history: Mutex::new(RateLimitHistory::default()),
        }
    }
}

struct VtRateState {
    limiter: Arc<RateLimiter>,
}

impl VtRateState {
    fn new() -> Self {
        Self {
            limiter: Arc::new(RateLimiter::new()),
        }
    }
}

static GENERATED_ID: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VTScanStatus {
    Clean,
    Detected,
    Error,
    Pending,
    RateLimited,
    NotFound,
    FileTooLarge,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VTDetection {
    pub engine_name: String,
    pub category: String,
    pub result: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VTScanResult {
    pub status: VTScanStatus,
    pub file_path: String,
    pub sha256: String,
    pub detections: u64,
    pub total_engines: u64,
    pub detection_details: Vec<VTDetection>,
    pub scan_date: Option<String>,
    pub permalink: Option<String>,
    pub error_message: Option<String>,
    pub duration: f64,
}

impl VTScanResult {
    fn empty(
        status: VTScanStatus,
        file_path: impl Into<String>,
        sha256: impl Into<String>,
    ) -> Self {
        Self {
            status,
            file_path: file_path.into(),
            sha256: sha256.into(),
            detections: 0,
            total_engines: 0,
            detection_details: Vec::new(),
            scan_date: None,
            permalink: None,
            error_message: None,
            duration: 0.0,
        }
    }

    pub fn is_clean(&self) -> bool {
        matches!(self.status, VTScanStatus::Clean | VTScanStatus::NotFound)
    }

    pub fn has_threats(&self) -> bool {
        self.status == VTScanStatus::Detected
    }

    pub fn is_error(&self) -> bool {
        matches!(
            self.status,
            VTScanStatus::Error | VTScanStatus::RateLimited | VTScanStatus::FileTooLarge
        )
    }

    fn error(
        file_path: impl Into<String>,
        sha256: impl Into<String>,
        message: &'static str,
    ) -> Self {
        let mut result = Self::empty(VTScanStatus::Error, file_path, sha256);
        result.error_message = Some(message.into());
        result
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpMethod {
    Get,
    Post,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FileIdentity {
    device: u64,
    inode: u64,
    size: u64,
    modified_seconds: i64,
    modified_nanoseconds: i64,
    changed_seconds: i64,
    changed_nanoseconds: i64,
}

impl FileIdentity {
    fn from_file(file: &File) -> Result<Self, TransportError> {
        let metadata = file.metadata().map_err(|_| TransportError::Other)?;
        if !metadata.file_type().is_file() {
            return Err(TransportError::Other);
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            size: metadata.len(),
            modified_seconds: metadata.mtime(),
            modified_nanoseconds: metadata.mtime_nsec(),
            changed_seconds: metadata.ctime(),
            changed_nanoseconds: metadata.ctime_nsec(),
        })
    }
}

#[derive(Debug, Clone)]
struct PinnedFile {
    file: Arc<Mutex<File>>,
    identity: FileIdentity,
    filename: String,
}

impl PinnedFile {
    fn open(path: &Path) -> Result<Self, &'static str> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(path)
            .map_err(|error| {
                if error.kind() == std::io::ErrorKind::NotFound {
                    "File not found"
                } else {
                    "Cannot access file"
                }
            })?;
        let identity = FileIdentity::from_file(&file).map_err(|_| "Path is not a regular file")?;
        let filename = path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("file")
            .to_owned();
        Ok(Self {
            file: Arc::new(Mutex::new(file)),
            identity,
            filename,
        })
    }

    fn unchanged(&self) -> bool {
        self.file
            .lock()
            .ok()
            .and_then(|file| FileIdentity::from_file(&file).ok())
            .is_some_and(|identity| identity == self.identity)
    }

    fn calculate_sha256(&self, cancelled: &std::sync::atomic::AtomicBool) -> AppResult<String> {
        let mut file = self
            .file
            .lock()
            .map_err(|_| "Cannot read file".to_owned())?;
        file.seek(SeekFrom::Start(0))
            .map_err(|_| "Cannot read file".to_owned())?;
        let mut digest = Sha256::new();
        let mut buffer = [0u8; 8192];
        loop {
            if cancelled.load(Ordering::Relaxed) {
                return Err("Scan cancelled".into());
            }
            let count = file.read(&mut buffer).map_err(|_| "Cannot read file")?;
            if count == 0 {
                break;
            }
            digest.update(&buffer[..count]);
        }
        Ok(format!("{:x}", digest.finalize()))
    }
}

#[derive(Debug, Clone)]
pub enum HttpBody {
    Empty,
    File {
        file: Arc<Mutex<File>>,
        identity: FileIdentity,
        filename: String,
        length: u64,
    },
}
#[derive(Debug, Clone)]
pub struct HttpRequest {
    pub method: HttpMethod,
    pub url: String,
    pub timeout: Duration,
    pub body: HttpBody,
}

#[derive(Debug, Clone)]
pub struct HttpResponse {
    pub status: u16,
    pub body: Vec<u8>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransportError {
    Timeout,
    Connection,
    Other,
}

/// Kept deliberately narrow so tests can assert real HTTP protocol decisions
/// without touching a keyring or network account.
pub trait HttpTransport: Send + Sync {
    fn execute(&self, request: HttpRequest) -> Result<HttpResponse, TransportError>;
}

struct ReqwestTransport {
    client: Client,
    api_key: HeaderValue,
}

impl ReqwestTransport {
    fn new(api_key: &str) -> AppResult<Self> {
        let api_key = HeaderValue::from_str(api_key).map_err(|_| "Invalid API key")?;
        let client = Client::builder()
            // Never inherit HTTP(S)_PROXY, ALL_PROXY, or REQUESTS_CA_BUNDLE.
            .no_proxy()
            .use_rustls_tls()
            .build()
            .map_err(|_| "Unable to initialize VirusTotal connection")?;
        Ok(Self { client, api_key })
    }
}
fn classify_transport_error(error: reqwest::Error) -> TransportError {
    if error.is_timeout() {
        TransportError::Timeout
    } else if error.is_connect() {
        TransportError::Connection
    } else {
        TransportError::Other
    }
}

impl HttpTransport for ReqwestTransport {
    fn execute(&self, request: HttpRequest) -> Result<HttpResponse, TransportError> {
        let builder = match request.method {
            HttpMethod::Get => self.client.get(&request.url),
            HttpMethod::Post => self.client.post(&request.url),
        }
        .timeout(request.timeout)
        .header("x-apikey", self.api_key.clone());

        let builder = match request.body {
            HttpBody::Empty => builder,
            HttpBody::File {
                file,
                identity,
                filename,
                length,
            } => {
                let mut upload = {
                    let source = file.lock().map_err(|_| TransportError::Other)?;
                    if FileIdentity::from_file(&source)? != identity {
                        return Err(TransportError::Other);
                    }
                    source.try_clone().map_err(|_| TransportError::Other)?
                };
                upload
                    .seek(SeekFrom::Start(0))
                    .map_err(|_| TransportError::Other)?;
                let part = multipart::Part::reader_with_length(upload, length).file_name(filename);
                builder.multipart(multipart::Form::new().part("file", part))
            }
        };

        let response = builder.send().map_err(classify_transport_error)?;
        let status = response.status().as_u16();
        let body = response.bytes().map_err(classify_transport_error)?.to_vec();
        Ok(HttpResponse { status, body })
    }
}

pub struct VirusTotalClient {
    base_url: String,
    transport: Arc<dyn HttpTransport>,
    limiter: Arc<RateLimiter>,
}

impl VirusTotalClient {
    pub fn new(api_key: &str) -> AppResult<Self> {
        Self::with_limiter(
            api_key,
            VT_API_BASE,
            Arc::new(ReqwestTransport::new(api_key)?),
            Arc::new(RateLimiter::new()),
        )
    }

    fn new_for_context(ctx: &Context, api_key: &str) -> AppResult<Self> {
        let state = ctx.shared_state(VtRateState::new)?;
        Self::with_limiter(
            api_key,
            VT_API_BASE,
            Arc::new(ReqwestTransport::new(api_key)?),
            Arc::clone(&state.limiter),
        )
    }

    pub fn with_transport(
        api_key: &str,
        base_url: impl Into<String>,
        transport: Arc<dyn HttpTransport>,
    ) -> AppResult<Self> {
        Self::with_limiter(api_key, base_url, transport, Arc::new(RateLimiter::new()))
    }

    fn with_limiter(
        api_key: &str,
        base_url: impl Into<String>,
        transport: Arc<dyn HttpTransport>,
        limiter: Arc<RateLimiter>,
    ) -> AppResult<Self> {
        if api_key.is_empty() {
            return Err("API key not configured".into());
        }
        Ok(Self {
            base_url: base_url.into().trim_end_matches('/').to_owned(),
            transport,
            limiter,
        })
    }

    pub fn calculate_sha256(
        path: &Path,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> AppResult<String> {
        PinnedFile::open(path)
            .map_err(str::to_owned)?
            .calculate_sha256(cancelled)
    }

    pub fn scan_file(
        &self,
        file_path: &str,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> VTScanResult {
        let started = Instant::now();
        let mut result = match path_from_wire(file_path) {
            Ok(path) => self.scan_file_inner(&path, file_path, cancelled),
            Err(_) => VTScanResult::error(file_path, "", "Invalid file path"),
        };
        result.duration = started.elapsed().as_secs_f64();
        result
    }

    fn scan_file_inner(
        &self,
        path: &Path,
        file_path: &str,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> VTScanResult {
        if cancelled.load(Ordering::Relaxed) {
            return VTScanResult::error(file_path, "", "Scan cancelled");
        }
        let file = match PinnedFile::open(path) {
            Ok(file) => file,
            Err(message) => return VTScanResult::error(file_path, "", message),
        };
        let size = file.identity.size;
        if size > VT_MAX_FILE_SIZE {
            let mut result = VTScanResult::empty(VTScanStatus::FileTooLarge, file_path, "");
            result.error_message = Some(format!(
                "File too large ({:.1}MB). Maximum size is 650MB",
                size as f64 / (1024.0 * 1024.0)
            ));
            return result;
        }
        if size == 0 {
            return VTScanResult::error(file_path, "", "Cannot scan empty files");
        }

        let sha256 = match file.calculate_sha256(cancelled) {
            Ok(sha256) if file.unchanged() => sha256,
            Ok(_) => return VTScanResult::error(file_path, "", "File changed while hashing"),
            Err(message) => {
                return VTScanResult::error(
                    file_path,
                    "",
                    if message == "Scan cancelled" {
                        "Scan cancelled"
                    } else {
                        "Cannot read file"
                    },
                )
            }
        };
        let mut result = self.check_file_hash(&sha256, cancelled);
        result.file_path = file_path.into();
        if result.status == VTScanStatus::NotFound {
            if !file.unchanged() {
                return VTScanResult::error(file_path, &sha256, "File changed before upload");
            }
            result = self.upload_file(&file, file_path, &sha256, size, cancelled);
        }
        result
    }

    fn check_file_hash(
        &self,
        sha256: &str,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> VTScanResult {
        let request = HttpRequest {
            method: HttpMethod::Get,
            url: format!("{}/files/{sha256}", self.base_url),
            timeout: VT_REQUEST_TIMEOUT,
            body: HttpBody::Empty,
        };
        match self.request(request, cancelled) {
            Err(RequestFailure::Cancelled) => VTScanResult::error("", sha256, "Scan cancelled"),
            Err(RequestFailure::RateLimited) => {
                let mut result = VTScanResult::empty(VTScanStatus::RateLimited, "", sha256);
                result.error_message = Some("API rate limit exceeded".into());
                result
            }
            Err(RequestFailure::Authentication) => {
                VTScanResult::error("", sha256, "Invalid API key")
            }
            Err(RequestFailure::Permission) => {
                VTScanResult::error("", sha256, "API key lacks required permissions")
            }
            Err(RequestFailure::Timeout) => {
                VTScanResult::error("", sha256, "Request timed out after retries")
            }
            Err(RequestFailure::Connection) => {
                VTScanResult::error("", sha256, "Network connection failed after retries")
            }
            Err(RequestFailure::Other) => VTScanResult::error("", sha256, "Request failed"),
            Ok(response) if response.status == 404 => {
                VTScanResult::empty(VTScanStatus::NotFound, "", sha256)
            }
            Ok(response) if response.status != 200 => {
                VTScanResult::error("", sha256, "API request failed")
            }
            Ok(response) => match serde_json::from_slice(&response.body) {
                Ok(value) => self.parse_file_report(&value, sha256),
                Err(_) => VTScanResult::error("", sha256, "Invalid JSON response from API"),
            },
        }
    }

    fn upload_file(
        &self,
        file: &PinnedFile,
        file_path: &str,
        sha256: &str,
        length: u64,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> VTScanResult {
        let upload_url = if length <= VT_DIRECT_UPLOAD_MAX {
            format!("{}/files", self.base_url)
        } else {
            let request = HttpRequest {
                method: HttpMethod::Get,
                url: format!("{}/files/upload_url", self.base_url),
                timeout: VT_REQUEST_TIMEOUT,
                body: HttpBody::Empty,
            };
            let response = match self.request(request, cancelled) {
                Ok(response) => response,
                Err(failure) => return request_failure_result(file_path, sha256, failure),
            };
            if response.status != 200 {
                return VTScanResult::error(
                    file_path,
                    sha256,
                    "Failed to obtain upload URL for large file",
                );
            }
            match serde_json::from_slice::<Value>(&response.body)
                .ok()
                .and_then(|value| value.get("data").and_then(Value::as_str).map(str::to_owned))
            {
                Some(url)
                    if url.starts_with("https://") || self.base_url.starts_with("http://") =>
                {
                    url
                }
                _ => {
                    return VTScanResult::error(
                        file_path,
                        sha256,
                        "Failed to obtain upload URL for large file",
                    )
                }
            }
        };

        if !file.unchanged() {
            return VTScanResult::error(file_path, sha256, "File changed before upload");
        }
        let request = HttpRequest {
            method: HttpMethod::Post,
            url: upload_url,
            timeout: VT_UPLOAD_TIMEOUT,
            body: HttpBody::File {
                file: Arc::clone(&file.file),
                identity: file.identity,
                filename: file.filename.clone(),
                length,
            },
        };
        let response = match self.request(request, cancelled) {
            Ok(response) if file.unchanged() => response,
            Ok(_) => return VTScanResult::error(file_path, sha256, "File changed during upload"),
            Err(failure) => return request_failure_result(file_path, sha256, failure),
        };
        if response.status != 200 {
            return VTScanResult::error(file_path, sha256, "Upload failed");
        }
        let analysis_id = serde_json::from_slice::<Value>(&response.body)
            .ok()
            .and_then(|value| value.get("data")?.get("id")?.as_str().map(str::to_owned));
        match analysis_id {
            Some(analysis_id) => self.poll_analysis(&analysis_id, file_path, sha256, cancelled),
            None => {
                if !interruptible_sleep(ANALYSIS_POLL_INTERVAL, cancelled) {
                    return VTScanResult::error(file_path, sha256, "Scan cancelled");
                }
                let mut result = self.check_file_hash(sha256, cancelled);
                result.file_path = file_path.into();
                result
            }
        }
    }

    fn poll_analysis(
        &self,
        analysis_id: &str,
        file_path: &str,
        sha256: &str,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> VTScanResult {
        let started = Instant::now();
        while started.elapsed() < ANALYSIS_MAX_WAIT {
            if cancelled.load(Ordering::Relaxed) {
                return VTScanResult::error(file_path, sha256, "Scan cancelled");
            }
            let request = HttpRequest {
                method: HttpMethod::Get,
                url: format!("{}/analyses/{analysis_id}", self.base_url),
                timeout: VT_REQUEST_TIMEOUT,
                body: HttpBody::Empty,
            };
            match self.request(request, cancelled) {
                Ok(response) if response.status == 200 => {
                    let state = serde_json::from_slice::<Value>(&response.body)
                        .ok()
                        .and_then(|value| {
                            value
                                .get("data")?
                                .get("attributes")?
                                .get("status")?
                                .as_str()
                                .map(str::to_owned)
                        });
                    if state.as_deref() == Some("completed") {
                        let mut result = self.check_file_hash(sha256, cancelled);
                        result.file_path = file_path.into();
                        return result;
                    }
                }
                Ok(_) | Err(_) => {
                    let mut result = self.check_file_hash(sha256, cancelled);
                    result.file_path = file_path.into();
                    return result;
                }
            }
            if !interruptible_sleep(ANALYSIS_POLL_INTERVAL, cancelled) {
                return VTScanResult::error(file_path, sha256, "Scan cancelled");
            }
        }
        let mut result = self.check_file_hash(sha256, cancelled);
        result.file_path = file_path.into();
        if result.status == VTScanStatus::NotFound {
            result.status = VTScanStatus::Pending;
            result.error_message = Some("Analysis still in progress".into());
        }
        result
    }

    fn parse_file_report(&self, value: &Value, sha256: &str) -> VTScanResult {
        let Some(attributes) = value.get("data").and_then(|data| data.get("attributes")) else {
            return VTScanResult::error(
                "",
                sha256,
                "Malformed response: missing report attributes",
            );
        };
        let stats = attributes
            .get("last_analysis_stats")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let malicious = stats.get("malicious").and_then(Value::as_u64).unwrap_or(0);
        let suspicious = stats.get("suspicious").and_then(Value::as_u64).unwrap_or(0);
        let total_engines = stats.values().filter_map(Value::as_u64).sum();
        let detection_details = attributes
            .get("last_analysis_results")
            .and_then(Value::as_object)
            .map(|results| {
                results
                    .iter()
                    .filter_map(|(engine_name, detail)| {
                        let category = detail.get("category")?.as_str()?;
                        (category == "malicious" || category == "suspicious").then(|| VTDetection {
                            engine_name: engine_name.clone(),
                            category: category.into(),
                            result: detail
                                .get("result")
                                .and_then(Value::as_str)
                                .map(str::to_owned),
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();
        let detections = malicious + suspicious;
        VTScanResult {
            status: if detections > 0 {
                VTScanStatus::Detected
            } else {
                VTScanStatus::Clean
            },
            file_path: String::new(),
            sha256: sha256.into(),
            detections,
            total_engines,
            detection_details,
            scan_date: attributes
                .get("last_analysis_date")
                .and_then(Value::as_i64)
                .and_then(unix_timestamp_iso8601),
            permalink: Some(format!("https://www.virustotal.com/gui/file/{sha256}")),
            error_message: None,
            duration: 0.0,
        }
    }

    fn request(
        &self,
        request: HttpRequest,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> Result<HttpResponse, RequestFailure> {
        self.wait_for_rate_limit(cancelled)?;
        for attempt in 0..VT_MAX_RETRIES {
            if cancelled.load(Ordering::Relaxed) {
                return Err(RequestFailure::Cancelled);
            }
            match self.transport.execute(request.clone()) {
                Ok(response) if response.status == 429 => return Err(RequestFailure::RateLimited),
                Ok(response) if response.status == 401 => {
                    return Err(RequestFailure::Authentication)
                }
                Ok(response) if response.status == 403 => return Err(RequestFailure::Permission),
                Ok(response) => return Ok(response),
                Err(TransportError::Timeout) if attempt + 1 == VT_MAX_RETRIES => {
                    return Err(RequestFailure::Timeout);
                }
                Err(TransportError::Connection) if attempt + 1 == VT_MAX_RETRIES => {
                    return Err(RequestFailure::Connection);
                }
                Err(TransportError::Other) => return Err(RequestFailure::Other),
                Err(TransportError::Timeout | TransportError::Connection) => {
                    let delay = VT_RETRY_BASE_DELAY.saturating_mul(1u32 << attempt);
                    if !interruptible_sleep(delay, cancelled) {
                        return Err(RequestFailure::Cancelled);
                    }
                }
            }
        }
        Err(RequestFailure::Other)
    }

    fn wait_for_rate_limit(
        &self,
        cancelled: &std::sync::atomic::AtomicBool,
    ) -> Result<(), RequestFailure> {
        loop {
            if cancelled.load(Ordering::Relaxed) {
                return Err(RequestFailure::Cancelled);
            }
            let wait = {
                let mut history = self
                    .limiter
                    .history
                    .lock()
                    .map_err(|_| RequestFailure::Other)?;
                let now = Instant::now();
                history
                    .minute_requests
                    .retain(|timestamp| now.duration_since(*timestamp) < VT_RATE_LIMIT_WINDOW);
                history.daily_requests.retain(|timestamp| {
                    now.duration_since(*timestamp) < VT_DAILY_RATE_LIMIT_WINDOW
                });
                if history.daily_requests.len() >= VT_DAILY_RATE_LIMIT_REQUESTS {
                    return Err(RequestFailure::RateLimited);
                }
                if history.minute_requests.len() < VT_RATE_LIMIT_REQUESTS {
                    history.minute_requests.push(now);
                    history.daily_requests.push(now);
                    return Ok(());
                }
                VT_RATE_LIMIT_WINDOW.saturating_sub(now.duration_since(history.minute_requests[0]))
            };
            if !interruptible_sleep(wait.min(Duration::from_secs(5)), cancelled) {
                return Err(RequestFailure::Cancelled);
            }
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum RequestFailure {
    Cancelled,
    RateLimited,
    Authentication,
    Permission,
    Timeout,
    Connection,
    Other,
}

fn tr(ctx: &Context, message: &str) -> String {
    crate::i18n::translate(ctx, message)
}

fn localize_result(ctx: &Context, result: &mut VTScanResult) {
    let Some(message) = result.error_message.take() else {
        return;
    };
    let localized = if let Some(size) = message
        .strip_prefix("File too large (")
        .and_then(|value| value.strip_suffix("MB). Maximum size is 650MB"))
    {
        tr(ctx, "File too large ({size}MB). Maximum size is {max}MB")
            .replace("{size}", size)
            .replace("{max}", "650")
    } else if message == "Invalid file path" {
        tr(ctx, "Invalid file path")
    } else if message == "Path is not a regular file" {
        tr(ctx, "Path is not a regular file")
    } else if message == "File changed while hashing" {
        tr(ctx, "File changed while hashing")
    } else if message == "File changed before upload" {
        tr(ctx, "File changed before upload")
    } else if message == "File changed during upload" {
        tr(ctx, "File changed during upload")
    } else {
        tr(ctx, &message)
    };
    result.error_message = Some(localized);
}

fn save_log(ctx: &Context, result: &VTScanResult) {
    let (status, summary) = match result.status {
        VTScanStatus::Clean => ("clean", tr(ctx, "VirusTotal: Clean scan")),
        VTScanStatus::Detected if result.detections > 0 && result.total_engines > 0 => (
            "infected",
            tr(
                ctx,
                "VirusTotal: {detections}/{total} engines detected threats",
            )
            .replace("{detections}", &result.detections.to_string())
            .replace("{total}", &result.total_engines.to_string()),
        ),
        VTScanStatus::Detected => ("infected", tr(ctx, "VirusTotal: Threats detected")),
        VTScanStatus::RateLimited => ("error", tr(ctx, "VirusTotal: Rate limit exceeded")),
        VTScanStatus::Pending => ("pending", tr(ctx, "VirusTotal: Analysis pending")),
        VTScanStatus::NotFound => (
            "unknown",
            tr(ctx, "VirusTotal: File not previously analyzed"),
        ),
        VTScanStatus::FileTooLarge => ("error", tr(ctx, "VirusTotal: File too large for upload")),
        VTScanStatus::Error => ("error", tr(ctx, "VirusTotal: Scan error")),
    };
    let mut details = Vec::new();
    if result.total_engines > 0 {
        details.push(
            tr(ctx, "Detections: {detections}/{total}")
                .replace("{detections}", &result.detections.to_string())
                .replace("{total}", &result.total_engines.to_string()),
        );
    }
    for detection in &result.detection_details {
        details.push(format!(
            "{} ({}): {}",
            detection.engine_name,
            detection.category,
            detection.result.as_deref().unwrap_or("unknown")
        ));
    }
    if let Some(error) = &result.error_message {
        details.push(tr(ctx, "Error: {error}").replace("{error}", error));
    }
    let _ = crate::logs::save(
        ctx,
        json!({
            "type": "virustotal",
            "status": status,
            "summary": summary,
            "details": details.join("\n"),
            "path": Value::Null,
            "duration": result.duration,
            "scheduled": false,
        }),
    );
}

fn request_failure_result(file_path: &str, sha256: &str, failure: RequestFailure) -> VTScanResult {
    match failure {
        RequestFailure::RateLimited => {
            let mut result = VTScanResult::empty(VTScanStatus::RateLimited, file_path, sha256);
            result.error_message = Some("API rate limit exceeded".into());
            result
        }
        RequestFailure::Cancelled => VTScanResult::error(file_path, sha256, "Scan cancelled"),
        RequestFailure::Authentication => VTScanResult::error(file_path, sha256, "Invalid API key"),
        RequestFailure::Permission => {
            VTScanResult::error(file_path, sha256, "API key lacks required permissions")
        }
        RequestFailure::Timeout => {
            VTScanResult::error(file_path, sha256, "Request timed out after retries")
        }
        RequestFailure::Connection => {
            VTScanResult::error(file_path, sha256, "Network connection failed after retries")
        }
        RequestFailure::Other => VTScanResult::error(file_path, sha256, "Request failed"),
    }
}

fn interruptible_sleep(duration: Duration, cancelled: &std::sync::atomic::AtomicBool) -> bool {
    let deadline = Instant::now() + duration;
    while Instant::now() < deadline {
        if cancelled.load(Ordering::Relaxed) {
            return false;
        }
        thread::sleep((deadline - Instant::now()).min(Duration::from_millis(100)));
    }
    !cancelled.load(Ordering::Relaxed)
}

fn unix_timestamp_iso8601(timestamp: i64) -> Option<String> {
    if timestamp < 0 {
        return None;
    }
    let days = timestamp.div_euclid(86_400);
    let seconds = timestamp.rem_euclid(86_400);
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    let year = year + i64::from(month <= 2);
    Some(format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}+00:00",
        seconds / 3600,
        (seconds % 3600) / 60,
        seconds % 60
    ))
}

fn required_string<'a>(args: &'a Value, key: &str) -> AppResult<&'a str> {
    args.get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("Missing required argument: {key}"))
}

fn generated_id() -> String {
    let sequence = GENERATED_ID.fetch_add(1, Ordering::Relaxed);
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("virustotal-{millis}-{sequence}")
}

/// Dispatches only the VirusTotal UI operation contract. It intentionally
/// returns the full report to the caller but never a credential.
pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "key_status" => {
            let info = CredentialStore::new(ctx).status(Account::VirusTotalApiKey)?;
            serde_json::to_value(info).map_err(|_| "Unable to serialize key status".into())
        }
        "key_save" => {
            let key = required_string(&args, "key")?;
            let store = CredentialStore::new(ctx);
            let write = store.set(Account::VirusTotalApiKey, key)?;
            let info = store.status(Account::VirusTotalApiKey)?;
            Ok(json!({
                "present": info.present,
                "backend": info.backend,
                "status": info.status,
                "masked": info.masked,
                "message": write.warning.unwrap_or_else(|| {
                    tr(
                        ctx,
                        // Translators: Keep `API` unchanged as the abbreviation for application programming interface.
                        "API key saved",
                    )
                }),
            }))
        }
        "key_delete" => {
            let store = CredentialStore::new(ctx);
            let deleted = store.delete(Account::VirusTotalApiKey)?;
            let info = store.status(Account::VirusTotalApiKey)?;
            let message = if deleted {
                "API key deleted"
            } else if info.status == crate::credentials::CredentialStatus::Locked {
                "System keyring is locked; no keyring item was deleted"
            } else {
                "No API key was configured"
            };
            let message = tr(ctx, message);
            Ok(json!({
                "present": info.present,
                "backend": info.backend,
                "status": info.status,
                "masked": info.masked,
                "message": message,
            }))
        }
        "scan" => {
            let path = required_string(&args, "path")?;
            let id = args
                .get("id")
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty())
                .map(str::to_owned)
                .unwrap_or_else(generated_id);
            let job = ctx.job(&id)?;
            let key = CredentialStore::new(ctx).get(Account::VirusTotalApiKey)?;
            let mut result = match key {
                Some(key) => {
                    VirusTotalClient::new_for_context(ctx, &key)?.scan_file(path, &job.cancelled)
                }
                None => VTScanResult::error(path, "", "API key not configured"),
            };
            localize_result(ctx, &mut result);
            save_log(ctx, &result);
            let result_value = serde_json::to_value(&result)
                .map_err(|_| "Unable to serialize VirusTotal result")?;
            ctx.emit(
                "virustotal-complete",
                json!({"id": id, "result": result_value.clone()}),
            );
            Ok(result_value)
        }
        "cancel" => {
            let id = required_string(&args, "id")?;
            Ok(json!({"cancelled": ctx.cancel(id)}))
        }
        _ => Err(format!("Unknown virustotal action: {action}")),
    }
}
