//! Localized scan-summary templates emitted by earlier ClamUI releases.
//!
//! This deliberately contains only the four summary keys that the log reader
//! recognizes. It preserves historical forms independently from the active PO
//! catalogs, whose obsolete entries are removed during normal gettext merges.

pub const TEMPLATES: &[(&str, &[&str])] = &[
    (
        "Scanned: {count} file\0Scanned: {count} files",
        &[
            "Gescannt: {count} Datei",
            "Gescannt: {count} Dateien",
            "Analizado: {count} archivo",
            "Analizado: {count} archivos",
            "Analyse\u{a0}: {count} fichier",
            "Analyse\u{a0}: {count} fichiers",
            "Megvizsgálva: {count} fájl",
            "Analizzato: {count} file",
            "Analizzati: {count} file",
            "Verificado: {count} arquivo",
            "Verificados: {count} arquivos",
            "已扫描 {count} 个文件",
        ],
    ),
    (
        "Threat found: {count}\0Threats found: {count}",
        &[
            "Bedrohung gefunden: {count}",
            "Bedrohungen gefunden: {count}",
            "Amenaza detectada: {count}",
            "Amenazas detectadas: {count}",
            "Menace détectée\u{a0}: {count}",
            "Menaces détectées\u{a0}: {count}",
            "Talált fenyegetés: {count}",
            "Talált fenyegetések: {count}",
            "Minaccia trovata: {count}",
            "Minacce trovate: {count}",
            "Ameaça encontrada: {count}",
            "Ameaças encontradas: {count}",
            "发现威胁：{count} 个",
        ],
    ),
    (
        "Files Scanned: {count}",
        &[
            "Gescannte Dateien: {count}",
            "Archivos escaneados: {count}",
            "Fichiers analysés : {count}",
            "Megvizsgált fájlok: {count}",
            "File Scansionati: {count}",
            "Arquivos verificados: {count}",
            "已扫描文件：{count} 个",
        ],
    ),
    (
        "Threats Found: {count}",
        &[
            "Gefundene Bedrohungen: {count}",
            "Amenazas detectadas: {count}",
            "Menaces détectées : {count}",
            "Talált fenyegetések: {count}",
            "Minacce Trovate: {count}",
            "Ameaças encontradas: {count}",
            "已发现威胁：{count} 个",
        ],
    ),
];
