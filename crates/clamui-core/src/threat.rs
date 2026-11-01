use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ThreatSeverity {
    Critical,
    High,
    Medium,
    Low,
}

impl ThreatSeverity {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
        }
    }
}

const CRITICAL: &[&str] = &["ransom", "rootkit", "bootkit", "cryptolocker", "wannacry"];
const HIGH: &[&str] = &[
    "trojan",
    "worm",
    "backdoor",
    "exploit",
    "downloader",
    "dropper",
    "keylogger",
];
const MEDIUM: &[&str] = &["adware", "pua", "pup", "spyware", "miner", "coinminer"];
const LOW: &[&str] = &[
    "eicar",
    "test-signature",
    "test.file",
    "heuristic",
    "generic",
];

/// Classifies the ClamAV signature name using the legacy priority order.
pub fn classify_severity(name: Option<&str>) -> ThreatSeverity {
    let name = name.unwrap_or_default().to_ascii_lowercase();
    for (patterns, severity) in [
        (CRITICAL, ThreatSeverity::Critical),
        (HIGH, ThreatSeverity::High),
        (MEDIUM, ThreatSeverity::Medium),
        (LOW, ThreatSeverity::Low),
    ] {
        if patterns.iter().any(|pattern| name.contains(pattern)) {
            return severity;
        }
    }
    ThreatSeverity::Medium
}

/// Maps a signature to the legacy, user-visible category.  Specific categories
/// always win over generic PUA/Virus labels; within a tier, first occurrence wins.
pub fn categorize(name: Option<&str>) -> String {
    let Some(name) = name.filter(|name| !name.is_empty()) else {
        return "Unknown".into();
    };
    let lower = name.to_ascii_lowercase();
    let high = [
        ("ransomware", "Ransomware"),
        ("ransom", "Ransomware"),
        ("rootkit", "Rootkit"),
        ("bootkit", "Rootkit"),
        ("trojan", "Trojan"),
        ("worm", "Worm"),
        ("backdoor", "Backdoor"),
        ("exploit", "Exploit"),
        ("adware", "Adware"),
        ("spyware", "Spyware"),
        ("keylogger", "Spyware"),
        ("eicar", "Test"),
        ("test-signature", "Test"),
        ("test.file", "Test"),
        ("macro", "Macro"),
        ("phish", "Phishing"),
        ("heuristic", "Heuristic"),
    ];
    if let Some((_, category)) = high
        .iter()
        .filter_map(|(pattern, category)| lower.find(pattern).map(|position| (position, *category)))
        .min_by_key(|(position, _)| *position)
    {
        return category.into();
    }

    let low = [("pua", "PUA"), ("pup", "PUA"), ("virus", "Virus")];
    low.iter()
        .filter_map(|(pattern, category)| lower.find(pattern).map(|position| (position, *category)))
        .min_by_key(|(position, _)| *position)
        .map(|(_, category)| category.into())
        .unwrap_or_else(|| "Virus".into())
}
