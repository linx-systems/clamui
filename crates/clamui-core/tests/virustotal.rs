use clamui_core::credentials::{
    attributes, mask_api_key, validate_virustotal_api_key, Account, SERVICE_NAME,
};
use clamui_core::virustotal::{
    HttpBody, HttpRequest, HttpResponse, HttpTransport, TransportError, VTScanStatus,
    VirusTotalClient,
};
use std::collections::VecDeque;
use std::ffi::CString;
use std::fs::{self, File};
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tempfile::TempDir;

#[derive(Default)]
struct FakeHttp {
    requests: Mutex<Vec<HttpRequest>>,
    responses: Mutex<VecDeque<Result<HttpResponse, TransportError>>>,
}

impl FakeHttp {
    fn scripted(responses: Vec<Result<HttpResponse, TransportError>>) -> Self {
        Self {
            requests: Mutex::new(Vec::new()),
            responses: Mutex::new(responses.into()),
        }
    }

    fn requests(&self) -> Vec<HttpRequest> {
        self.requests.lock().unwrap().clone()
    }
}

impl HttpTransport for FakeHttp {
    fn execute(&self, request: HttpRequest) -> Result<HttpResponse, TransportError> {
        self.requests.lock().unwrap().push(request);
        self.responses
            .lock()
            .unwrap()
            .pop_front()
            .expect("fake protocol response was not scripted")
    }
}
struct SwapAfterLookupHttp {
    selected: PathBuf,
    replacement: PathBuf,
    requests: Mutex<Vec<HttpRequest>>,
    responses: Mutex<VecDeque<Result<HttpResponse, TransportError>>>,
    swapped: AtomicBool,
}

impl SwapAfterLookupHttp {
    fn scripted(
        selected: PathBuf,
        replacement: PathBuf,
        responses: Vec<Result<HttpResponse, TransportError>>,
    ) -> Self {
        Self {
            selected,
            replacement,
            requests: Mutex::new(Vec::new()),
            responses: Mutex::new(responses.into()),
            swapped: AtomicBool::new(false),
        }
    }

    fn requests(&self) -> Vec<HttpRequest> {
        self.requests.lock().unwrap().clone()
    }
}

impl HttpTransport for SwapAfterLookupHttp {
    fn execute(&self, request: HttpRequest) -> Result<HttpResponse, TransportError> {
        if matches!(&request.body, HttpBody::Empty)
            && request.url.contains("/files/")
            && !self.swapped.swap(true, Ordering::SeqCst)
        {
            fs::remove_file(&self.selected).unwrap();
            symlink(&self.replacement, &self.selected).unwrap();
        }
        self.requests.lock().unwrap().push(request);
        self.responses
            .lock()
            .unwrap()
            .pop_front()
            .expect("fake protocol response was not scripted")
    }
}

fn json_response(status: u16, value: &str) -> Result<HttpResponse, TransportError> {
    Ok(HttpResponse {
        status,
        body: value.as_bytes().to_vec(),
    })
}

fn fixture_dir() -> TempDir {
    tempfile::tempdir().unwrap()
}

fn temporary_file(directory: &TempDir, name: &str, contents: &[u8]) -> PathBuf {
    let path = directory.path().join(name);
    let mut file = File::create(&path).unwrap();
    file.write_all(contents).unwrap();
    path
}

fn report(malicious: u64, suspicious: u64) -> String {
    serde_json::json!({
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "undetected": 50,
                    "timeout": 2,
                    "custom_bucket": 3,
                },
                "last_analysis_results": {
                    "Engine A": {"category": "malicious", "result": "Example"},
                    "Engine B": {"category": "suspicious", "result": null},
                    "Engine C": {"category": "undetected", "result": null},
                },
                "last_analysis_date": 0,
            }
        }
    })
    .to_string()
}

#[test]
fn credential_attributes_and_key_format_match_python_keyring_records() {
    let vt_attributes = attributes(Account::VirusTotalApiKey);
    assert_eq!(vt_attributes.get("service"), Some(&SERVICE_NAME));
    assert_eq!(vt_attributes.get("username"), Some(&"virustotal_api_key"));
    assert_eq!(
        attributes(Account::PortmasterApiToken).get("username"),
        Some(&"portmaster_api_token")
    );

    assert!(validate_virustotal_api_key(&"A1".repeat(32)).is_ok());
    assert!(validate_virustotal_api_key(&"a".repeat(63)).is_err());
    assert!(validate_virustotal_api_key(&format!("{}g", "a".repeat(63))).is_err());
    assert_eq!(mask_api_key(Some("abcdef0123456789")), "abcdef01...");
    assert_eq!(mask_api_key(Some("short")), "****");
    assert_eq!(mask_api_key(None), "Not set");
}

#[test]
fn fake_http_hash_lookup_projects_all_engine_buckets_without_uploading() {
    let fake = Arc::new(FakeHttp::scripted(vec![json_response(200, &report(1, 1))]));
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();
    let fixture = fixture_dir();
    let path = temporary_file(&fixture, "known", b"known");
    let result = client.scan_file(path.to_str().unwrap(), &AtomicBool::new(false));

    assert_eq!(result.status, VTScanStatus::Detected);
    assert_eq!(result.detections, 2);
    assert_eq!(result.total_engines, 57);
    assert_eq!(result.detection_details.len(), 2);
    assert_eq!(
        result.scan_date.as_deref(),
        Some("1970-01-01T00:00:00+00:00")
    );
    let requests = fake.requests();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].url.contains("/files/"));
    assert!(matches!(requests[0].body, HttpBody::Empty));
}

#[test]
fn scan_accepts_percent_encoded_local_file_uri_without_changing_result_identity() {
    let fake = Arc::new(FakeHttp::scripted(vec![json_response(200, &report(0, 0))]));
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();
    let fixture = fixture_dir();
    let path = temporary_file(&fixture, "scan target", b"known URI sample");
    let uri = format!("file://{}", path.to_str().unwrap().replace(' ', "%20"));

    let result = client.scan_file(&uri, &AtomicBool::new(false));

    assert_eq!(result.status, VTScanStatus::Clean);
    assert_eq!(result.file_path, uri);
    assert_eq!(fake.requests().len(), 1);
}

#[test]
fn fake_http_unknown_file_uses_direct_streaming_upload_then_poll_and_hash_lookup() {
    let fake = Arc::new(FakeHttp::scripted(vec![
        json_response(404, "{}"),
        json_response(200, r#"{"data":{"id":"analysis-123"}}"#),
        json_response(200, r#"{"data":{"attributes":{"status":"completed"}}}"#),
        json_response(200, &report(0, 0)),
    ]));
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();
    let fixture = fixture_dir();
    let path = temporary_file(&fixture, "unknown", b"previously unknown content");
    let result = client.scan_file(path.to_str().unwrap(), &AtomicBool::new(false));

    assert_eq!(result.status, VTScanStatus::Clean);
    let requests = fake.requests();
    assert_eq!(requests.len(), 4);
    assert!(requests[0].url.contains("/files/"));
    assert!(requests[1].url.ends_with("/files"));
    assert!(matches!(requests[1].body, HttpBody::File { .. }));
    assert!(requests[2].url.ends_with("/analyses/analysis-123"));
    assert!(requests[3].url.contains("/files/"));
}

#[test]
fn path_substitution_is_rejected_before_upload() {
    let fixture = fixture_dir();
    let selected = temporary_file(&fixture, "selected", b"selected sample");
    let replacement = temporary_file(&fixture, "replacement", b"replacement bytes");
    let fake = Arc::new(SwapAfterLookupHttp::scripted(
        selected.clone(),
        replacement,
        vec![json_response(404, "{}")],
    ));
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();

    let result = client.scan_file(selected.to_str().unwrap(), &AtomicBool::new(false));

    assert_eq!(result.status, VTScanStatus::Error);
    assert_eq!(
        result.error_message.as_deref(),
        Some("File changed before upload")
    );
    let requests = fake.requests();
    assert_eq!(requests.len(), 1);
    assert!(matches!(requests[0].body, HttpBody::Empty));
}

#[test]
fn fake_http_large_file_requests_one_time_url_before_streaming_upload() {
    let fake = Arc::new(FakeHttp::scripted(vec![
        json_response(404, "{}"),
        json_response(200, r#"{"data":"http://fake/upload-once"}"#),
        json_response(200, "{}"),
        json_response(200, &report(0, 0)),
    ]));
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();
    let fixture = fixture_dir();
    let path = temporary_file(&fixture, "large", &[]);
    File::options()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len(32 * 1024 * 1024 + 1)
        .unwrap();
    let result = client.scan_file(path.to_str().unwrap(), &AtomicBool::new(false));

    assert_eq!(result.status, VTScanStatus::Clean);
    let requests = fake.requests();
    assert_eq!(requests.len(), 4);
    assert!(requests[1].url.ends_with("/files/upload_url"));
    assert_eq!(requests[2].url, "http://fake/upload-once");
    assert!(matches!(requests[2].body, HttpBody::File { length, .. } if length > 32 * 1024 * 1024));
}

#[test]
fn fifo_is_rejected_without_blocking_or_contacting_transport() {
    let fake = Arc::new(FakeHttp::default());
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();
    let fixture = fixture_dir();
    let path = fixture.path().join("sample.fifo");
    let path_c = CString::new(path.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(path_c.as_ptr(), 0o600) }, 0);

    let result = client.scan_file(path.to_str().unwrap(), &AtomicBool::new(false));

    assert_eq!(result.status, VTScanStatus::Error);
    assert_eq!(
        result.error_message.as_deref(),
        Some("Path is not a regular file")
    );
    assert!(fake.requests().is_empty());
}

#[test]
fn cancelled_operation_never_uses_transport() {
    let fake = Arc::new(FakeHttp::default());
    let client =
        VirusTotalClient::with_transport("a1", "http://fake/api/v3", fake.clone()).unwrap();
    let fixture = fixture_dir();
    let path = temporary_file(&fixture, "cancelled", b"cancelled");
    let result = client.scan_file(path.to_str().unwrap(), &AtomicBool::new(true));

    assert_eq!(result.status, VTScanStatus::Error);
    assert_eq!(result.error_message.as_deref(), Some("Scan cancelled"));
    assert!(fake.requests().is_empty());
}
