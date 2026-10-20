use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use clamui_core::{logs, Context, Paths};
use serde_json::{json, Value};
use std::{
    fs,
    io::{Cursor, Read},
};
use tempfile::TempDir;

fn context() -> (TempDir, Context) {
    let temp = TempDir::new().expect("temporary history root");
    let root = temp.path();
    let context = Context::with_paths(Paths {
        home: root.join("home"),
        config_dir: root.join("config/clamui"),
        data_dir: root.join("data/clamui"),
    })
    .expect("context");
    (temp, context)
}

#[test]
fn save_migrates_legacy_history_and_never_persists_private_values() {
    let (_temp, context) = context();
    let logs_dir = context.paths.data_dir.join("logs");
    fs::create_dir_all(&logs_dir).expect("legacy log directory");
    fs::write(
        logs_dir.join("legacy.json"),
        serde_json::to_vec_pretty(&json!({
            "id": "legacy",
            "timestamp": "2024-01-01T00:00:00",
            "type": "scan",
            "status": "infected",
            "summary": "Scanned /private/target",
            "details": "token=super-secret\n/private/target: Example.Threat FOUND",
            "path": "/private/target",
            "duration": "not-a-number",
        }))
        .expect("legacy JSON"),
    )
    .expect("legacy write");

    let entries = logs::dispatch(&context, "list", json!({"limit": 10})).expect("legacy list");
    let entry = entries
        .as_array()
        .expect("entry array")
        .first()
        .expect("legacy entry");
    assert_eq!(entry["path"], Value::Null);
    assert_eq!(entry["duration"], 0.0);
    assert!(!entry.to_string().contains("/private/target"));
    assert!(!entry.to_string().contains("super-secret"));
    assert!(entry.to_string().contains("Example.Threat"));
    assert_eq!(
        fs::read_to_string(logs_dir.join(".log-privacy-version")).expect("migration marker"),
        "1"
    );
    assert!(!fs::read_to_string(logs_dir.join("legacy.json"))
        .expect("migrated data")
        .contains("/private/target"));

    let saved = logs::save(&context, json!({
        "type": "scan", "status": "infected", "path": "/another/private/path",
        "summary": "Found /another/private/path", "details": "api_key=secret-value\n- Malware.Name",
        "infected_count": 1, "duration": 2.5,
    }))
    .expect("save privacy-safe history");
    assert_eq!(saved["path"], Value::Null);
    assert!(!saved.to_string().contains("/another/private/path"));
    assert!(!saved.to_string().contains("secret-value"));
    assert!(saved.to_string().contains("Malware.Name"));
}

#[test]
fn list_recovers_from_corrupt_index_and_skips_corrupt_entries() {
    let (_temp, context) = context();
    let saved = logs::save(
        &context,
        json!({"type":"update", "status":"success", "summary":"Updated", "details":"ok"}),
    )
    .expect("save");
    let logs_dir = context.paths.data_dir.join("logs");
    fs::write(logs_dir.join("log_index.json"), b"not JSON").expect("corrupt index");
    fs::write(logs_dir.join("broken.json"), b"{").expect("corrupt entry");

    let entries = logs::dispatch(&context, "list", json!({"limit": 100})).expect("recovered list");
    assert_eq!(entries.as_array().expect("array").len(), 1);
    assert_eq!(entries[0]["id"], saved["id"]);
    let rebuilt: Value =
        serde_json::from_slice(&fs::read(logs_dir.join("log_index.json")).expect("rebuilt index"))
            .expect("valid rebuilt index");
    assert_eq!(rebuilt["version"], 1);
    assert_eq!(
        rebuilt["entries"].as_array().expect("index entries").len(),
        1
    );
}

#[test]
fn exports_preserve_legacy_wrappers_without_private_paths() {
    let (_temp, context) = context();
    let saved = logs::save(&context, json!({
        "type":"scan", "status":"clean", "path":"/home/alice/private",
        "summary":"Clean scan", "details":"Scanned: 12 files, 3 directories", "duration":4.25, "scheduled":true,
    })).expect("save");

    let csv = logs::dispatch(
        &context,
        "export",
        json!({"format":"csv", "ids":[saved["id"]]}),
    )
    .expect("CSV export");
    let csv = csv.as_str().expect("CSV text");
    assert!(csv.starts_with("id,timestamp,type,status,path,summary,duration,scheduled\n"));
    assert!(csv.contains(",,Clean scan,4.25,true"));
    assert!(!csv.contains("/home/alice/private"));

    let json_export =
        logs::dispatch(&context, "export", json!({"format":"json"})).expect("JSON export");
    let export: Value =
        serde_json::from_str(json_export.as_str().expect("JSON text")).expect("export JSON");
    assert_eq!(export["count"], 1);
    assert_eq!(export["entries"][0]["path"], Value::Null);
    assert!(export.get("export_timestamp").is_some());

    let text = logs::dispatch(&context, "export", json!({"format":"text"})).expect("text export");
    assert!(text.as_str().expect("text").contains("Scanned: 12 files"));
}

#[test]
fn statistics_preserves_historical_localized_counts() {
    let (_temp, context) = context();
    let logs_dir = context.paths.data_dir.join("logs");
    fs::create_dir_all(&logs_dir).expect("logs directory");
    let timestamp = chrono::Local::now().to_rfc3339();
    for (index, details) in [
        "Scanned: 1 file, 0 directories",
        "Gescannt: 2 Dateien, 0 Verzeichnisse",
        "Analizado: 3 archivos, 0 directorios",
        "Analyse\u{a0}: 4 fichiers, 0 dossiers",
        "Megvizsgálva: 5 fájl, 0 könyvtár",
        "Analizzati: 6 file, 0 directory",
        "Verificados: 7 arquivos, 0 diretórios",
        "已扫描 8 个文件，0 个目录",
        "Gescannte Dateien: 9",
        "Archivos escaneados: 10",
    ]
    .into_iter()
    .enumerate()
    {
        fs::write(
            logs_dir.join(format!("legacy-{index}.json")),
            serde_json::to_vec(&json!({
                "id": format!("legacy-{index}"),
                "timestamp": timestamp,
                "type": "scan",
                "status": "clean",
                "summary": "Scan complete",
                "details": details,
                "path": null,
                "duration": 0.0,
                "scheduled": false,
            }))
            .expect("legacy scan"),
        )
        .expect("write legacy scan");
    }
    for (index, details) in [
        "Threats found: 1",
        "Bedrohungen gefunden: 2",
        "Amenazas detectadas: 3",
        "Menaces détectées\u{a0}: 4",
        "Talált fenyegetések: 5",
        "Minacce trovate: 6",
        "Ameaças encontradas: 7",
        "发现威胁：8 个",
        "Gefundene Bedrohungen: 9",
        "Ameaças encontradas: 10",
    ]
    .into_iter()
    .enumerate()
    {
        fs::write(
            logs_dir.join(format!("legacy-threat-{index}.json")),
            serde_json::to_vec(&json!({
                "id": format!("legacy-threat-{index}"),
                "timestamp": timestamp,
                "type": "scan",
                "status": "infected",
                "summary": "Scan complete",
                "details": details,
                "path": null,
                "duration": 0.0,
                "scheduled": false,
            }))
            .expect("legacy threat scan"),
        )
        .expect("write legacy threat scan");
    }
    let saved = logs::save(
        &context,
        json!({
            "type": "scan",
            "status": "infected",
            "summary": "Scan complete",
            "details": "Threats found: 999",
            "scanned_files": 9,
            "infected_count": 3,
        }),
    )
    .expect("save structured scan");
    assert!(saved.get("scanned_files").is_none());
    assert!(saved.get("infected_count").is_none());

    let stats =
        logs::dispatch(&context, "statistics", json!({"timeframe":"all"})).expect("statistics");
    assert_eq!(stats["files_scanned"], 64);
    assert_eq!(stats["threats_detected"], 58);
}

#[test]
fn statistics_respects_timeframe_boundaries_and_reports_real_trends() {
    let (_temp, context) = context();
    let now = chrono::Local::now();
    let manual_time = now - chrono::Duration::hours(11);
    let scheduled_time = now - chrono::Duration::hours(5);
    let old_time = now - chrono::Duration::days(8);
    let future_time = now + chrono::Duration::days(2);
    for (timestamp, status, scheduled, threats) in [
        (manual_time.to_rfc3339(), "clean", false, 0),
        (scheduled_time.to_rfc3339(), "infected", true, 2),
        (old_time.to_rfc3339(), "error", false, 0),
        (future_time.to_rfc3339(), "clean", false, 0),
    ] {
        logs::save(&context, json!({
            "type":"scan", "timestamp":timestamp, "status":status, "scheduled":scheduled,
            "summary":"Scan", "details":format!("Scanned: 10 files, 1 directories\nThreats found: {threats}"), "duration":10.0,
        })).expect("save scan");
    }

    let stats =
        logs::dispatch(&context, "statistics", json!({"timeframe":"day"})).expect("statistics");
    assert_eq!(stats["total_scans"], 2);
    assert_eq!(stats["files_scanned"], 20);
    assert_eq!(stats["threats_detected"], 2);
    assert_eq!(stats["infected_scans"], 1);
    assert_eq!(stats["scheduled_scans"], 1);
    assert_eq!(stats["manual_scans"], 1);
    let trends = stats["trends"].as_array().expect("trends");
    let today = now.date_naive();
    let dates = [
        (today - chrono::Duration::days(1))
            .format("%Y-%m-%d")
            .to_string(),
        today.format("%Y-%m-%d").to_string(),
    ];
    assert_eq!(
        trends
            .iter()
            .map(|trend| trend["date"].as_str().expect("date"))
            .collect::<Vec<_>>(),
        dates.iter().map(String::as_str).collect::<Vec<_>>()
    );
    for date in dates {
        let bucket = trends
            .iter()
            .find(|trend| trend["date"].as_str() == Some(date.as_str()))
            .expect("calendar trend bucket");
        let bucket_date =
            chrono::NaiveDate::parse_from_str(bucket["date"].as_str().expect("date"), "%Y-%m-%d")
                .expect("calendar date");
        let expected_scans = (manual_time.date_naive() == bucket_date) as u64
            + (scheduled_time.date_naive() == bucket_date) as u64;
        let expected_threats = if scheduled_time.date_naive() == bucket_date {
            2
        } else {
            0
        };
        assert_eq!(bucket["scans"], expected_scans);
        assert_eq!(bucket["threats"], expected_threats);
        assert!(bucket_date <= today);
    }
    assert_eq!(stats["protection_status"]["level"], "protected");
    assert_eq!(stats["last_scan"]["type"], "scan");
}
#[test]
fn debug_archive_contains_only_redacted_rotating_log_content() {
    let (_temp, context) = context();
    logs::write_debug(
        &context,
        "ERROR",
        "scanner",
        "failed /home/alice/document.txt api_key=top-secret",
    )
    .expect("debug write");
    let exported = logs::dispatch(&context, "debug_export", json!({})).expect("debug export");
    assert!(exported["filename"]
        .as_str()
        .expect("name")
        .starts_with("clamui-logs-"));
    let bytes = BASE64
        .decode(exported["content_base64"].as_str().expect("base64"))
        .expect("archive bytes");
    let mut archive = zip::ZipArchive::new(Cursor::new(bytes)).expect("ZIP archive");
    let mut content = String::new();
    archive
        .by_name("clamui.log")
        .expect("current debug log")
        .read_to_string(&mut content)
        .expect("debug content");
    assert!(content.contains("[REDACTED_PATH]"));
    assert!(content.contains("[REDACTED_SECRET]"));
    assert!(!content.contains("/home/alice/document.txt"));
    assert!(!content.contains("top-secret"));
}

#[test]
fn redaction_covers_paths_with_spaces_while_retaining_sanitized_threat_names() {
    let (_temp, context) = context();
    let saved = logs::save(
        &context,
        json!({
            "type": "scan",
            "status": "infected",
            "infected_count": 1,
            "threat_details": [{"threat_name": "Eicar-Test-Signature"}],
            "summary": "Scan completed",
            "details": "Result /home/alice/Private Folder/report.txt finished successfully",
        }),
    )
    .expect("save redacted scan");

    assert_eq!(
        saved["details"],
        "Result [REDACTED_PATH] finished successfully"
    );
    assert!(saved["details"]
        .as_str()
        .expect("details")
        .contains("finished successfully"));

    let generated = logs::save(&context, json!({
        "type": "scan", "status": "infected", "infected_count": 1,
        "threat_details": [{"threat_name": "Eicar-Test-Signature", "file_path": "/home/alice/Private Folder/eicar.txt"}],
    })).expect("save generated scan details");
    assert!(generated["details"]
        .as_str()
        .expect("generated details")
        .contains("Eicar-Test-Signature"));
    assert!(!generated
        .to_string()
        .contains("/home/alice/Private Folder/eicar.txt"));

    let preserved = logs::save(
        &context,
        json!({
            "type": "update",
            "status": "success",
            "summary": "Fetched update",
            "details": "Downloaded https://updates.example.test/file with checksum 0123456789abcdef0123456789abcdef; ordinary text remains.",
        }),
    )
    .expect("save URL and hash");
    let details = preserved["details"].as_str().expect("details");
    assert!(details.contains("[REDACTED_URL]"));
    assert!(details.contains("[REDACTED_HASH]"));
    assert!(details.contains("ordinary text remains."));
}

#[test]
fn ui_exports_use_legacy_ui_shapes_without_changing_cli_exports() {
    let (_temp, context) = context();
    let saved = logs::save(
        &context,
        json!({
            "type": "scan", "status": "clean", "summary": "Scan complete",
            "details": "Scanned: 3 files, 1 directories", "duration": 2.5,
        }),
    )
    .expect("save");

    let csv = logs::dispatch(&context, "export", json!({"schema": "ui", "format": "csv"}))
        .expect("UI CSV");
    assert!(csv
        .as_str()
        .expect("CSV")
        .starts_with("timestamp,type,status,path,summary,duration\n"));

    let selected = logs::dispatch(
        &context,
        "export",
        json!({"schema": "ui", "format": "json", "ids": [saved["id"]]}),
    )
    .expect("selected UI JSON");
    let selected: Value = serde_json::from_str(selected.as_str().expect("JSON")).expect("record");
    assert_eq!(selected["id"], saved["id"]);
    assert!(selected.get("entries").is_none());

    let all = logs::dispatch(
        &context,
        "export",
        json!({"schema": "ui", "format": "json"}),
    )
    .expect("all UI JSON");
    let all: Value = serde_json::from_str(all.as_str().expect("JSON")).expect("array");
    assert!(all.is_array());

    let text = logs::dispatch(
        &context,
        "export",
        json!({"schema": "ui", "format": "text", "ids": [saved["id"]]}),
    )
    .expect("UI text");
    assert!(!text.as_str().expect("text").is_empty());
}

#[test]
fn clear_removes_entries_and_reports_a_machine_readable_result() {
    let (_temp, context) = context();
    logs::save(
        &context,
        json!({"type":"update", "status":"success", "summary":"Updated", "details":"done"}),
    )
    .expect("save first log");
    logs::save(
        &context,
        json!({"type":"scan", "status":"clean", "summary":"Clean", "details":"Scanned: 1 files"}),
    )
    .expect("save second log");

    let result = logs::dispatch(&context, "clear", json!({})).expect("clear logs");
    assert_eq!(result["cleared"], 2);
    assert_eq!(result["success"], true);
    assert!(result["failures"]
        .as_array()
        .expect("failure list")
        .is_empty());
    assert_eq!(
        logs::dispatch(&context, "count", json!({})).expect("count")["total_entries"],
        0
    );
}
