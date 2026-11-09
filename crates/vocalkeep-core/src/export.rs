//! Backups, restores and the legacy-messages folder.
//!
//! A backup is a zip of the bank folder (`bank.json` plus every recording), ready to copy to a
//! computer with a graphics card for training, or to keep somewhere safe. Legacy messages are
//! exported as ordinary WAV files with a small offline web page to play them, so a family can
//! open them on any computer in twenty years without Vocalkeep.

use std::collections::HashSet;
use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::{Component, Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::Serialize;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

use crate::bank::{Bank, LegacyMessage, BANK_FORMAT, MANIFEST};

/// Largest restore we accept: about 40 hours of 48 kHz speech.
const MAX_RESTORE_BYTES: u64 = 16 * 1024 * 1024 * 1024;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportSummary {
    pub path: String,
    pub files: usize,
    pub bytes: u64,
}

/// Writes the whole bank to a zip file.
pub fn backup_zip(bank: &Bank, dest: &Path) -> Result<ExportSummary> {
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = dest.with_extension("zip.part");
    let file = File::create(&tmp).with_context(|| format!("creating {}", tmp.display()))?;
    let mut zip = ZipWriter::new(BufWriter::new(file));
    let folder = format!(
        "Vocalkeep voice bank{}",
        if bank.manifest.speaker.name.trim().is_empty() {
            String::new()
        } else {
            format!(" - {}", file_safe(&bank.manifest.speaker.name))
        }
    );
    let deflate = SimpleFileOptions::default()
        .compression_method(CompressionMethod::Deflated)
        .large_file(true);
    // WAV audio barely compresses; storing it keeps backups fast.
    let stored = SimpleFileOptions::default()
        .compression_method(CompressionMethod::Stored)
        .large_file(true);

    let mut files = 0;
    let mut bytes = 0u64;
    let manifest = serde_json::to_vec_pretty(&bank.manifest)?;
    zip.start_file(format!("{folder}/{MANIFEST}"), deflate)?;
    zip.write_all(&manifest)?;
    files += 1;
    bytes += manifest.len() as u64;

    let mut seen = HashSet::new();
    let referenced = bank
        .manifest
        .takes
        .iter()
        .map(|t| t.file.as_str())
        .chain(bank.manifest.legacy.iter().map(|m| m.file.as_str()));
    for rel in referenced {
        if !seen.insert(rel.to_string()) {
            continue;
        }
        let path = bank.resolve(rel)?;
        let Ok(mut input) = File::open(&path) else {
            log::warn!("{} is missing from the bank; skipped", path.display());
            continue;
        };
        zip.start_file(format!("{folder}/{rel}"), stored)?;
        bytes += io::copy(&mut input, &mut zip)?;
        files += 1;
    }
    zip.finish()?.flush()?;
    fs::rename(&tmp, dest).with_context(|| format!("saving {}", dest.display()))?;
    Ok(ExportSummary {
        path: dest.display().to_string(),
        files,
        bytes,
    })
}

/// Restores a backup zip into `dest` (which must not already hold a bank) and opens it.
pub fn restore_zip(zip_path: &Path, dest: &Path) -> Result<Bank> {
    if dest.join(MANIFEST).exists() {
        bail!("{} already holds a voice bank", dest.display());
    }
    let file = File::open(zip_path).with_context(|| format!("opening {}", zip_path.display()))?;
    let mut archive = ZipArchive::new(BufReader::new(file)).context("this isn't a zip file")?;

    // Find bank.json: at the top, or inside one folder.
    let mut prefix: Option<PathBuf> = None;
    for i in 0..archive.len() {
        let entry = archive.by_index(i)?;
        let Some(name) = entry.enclosed_name() else {
            continue;
        };
        if name.file_name().is_some_and(|f| f == MANIFEST) && name.components().count() <= 2 {
            prefix = Some(name.parent().map(Path::to_path_buf).unwrap_or_default());
            break;
        }
    }
    let Some(prefix) = prefix else {
        bail!("this zip doesn't contain a Vocalkeep voice bank (no bank.json)");
    };

    let mut total = 0u64;
    fs::create_dir_all(dest)?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)?;
        let Some(name) = entry.enclosed_name() else {
            bail!("the backup contains an unsafe path");
        };
        let Ok(rel) = name.strip_prefix(&prefix) else {
            continue;
        };
        if rel.as_os_str().is_empty()
            || rel.components().any(|c| !matches!(c, Component::Normal(_)))
        {
            continue;
        }
        let out = dest.join(rel);
        if entry.is_dir() {
            fs::create_dir_all(&out)?;
            continue;
        }
        if let Some(parent) = out.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut writer = BufWriter::new(File::create(&out)?);
        let mut limited = (&mut entry).take(MAX_RESTORE_BYTES - total + 1);
        total += io::copy(&mut limited, &mut writer)?;
        if total > MAX_RESTORE_BYTES {
            bail!("this backup is too large to restore");
        }
    }
    let bank = Bank::open(dest)?;
    if bank.manifest.format != BANK_FORMAT {
        bail!("this isn't a Vocalkeep voice bank");
    }
    Ok(bank)
}

/// Copies legacy messages to `dest_dir/<folder>/` as WAV files with an offline player page.
pub fn export_legacy(bank: &Bank, dest_dir: &Path) -> Result<ExportSummary> {
    let name = bank.manifest.speaker.name.trim();
    let folder = if name.is_empty() {
        "Legacy messages".to_string()
    } else {
        format!("Legacy messages from {}", file_safe(name))
    };
    let out = unique_dir(&dest_dir.join(folder));
    fs::create_dir_all(&out).with_context(|| format!("creating {}", out.display()))?;

    let mut messages: Vec<&LegacyMessage> = bank.manifest.legacy.iter().collect();
    messages.sort_by(|a, b| a.recorded_at.cmp(&b.recorded_at));

    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    struct Entry<'a> {
        file: String,
        title: &'a str,
        recipient: &'a str,
        occasion: &'a str,
        recorded_by: &'a str,
        note: &'a str,
        recorded_at: &'a str,
        duration_ms: u32,
    }
    let mut entries = Vec::new();
    let mut bytes = 0u64;
    for (i, m) in messages.iter().enumerate() {
        let mut label = format!("{:02} - {}", i + 1, file_safe(&m.title));
        if !m.recipient.is_empty() {
            label.push_str(&format!(" (for {})", file_safe(&m.recipient)));
        }
        let file = format!("{}.wav", truncate(&label, 100));
        let src = bank.resolve(&m.file)?;
        bytes += fs::copy(&src, out.join(&file))
            .with_context(|| format!("copying {}", src.display()))?;
        entries.push(Entry {
            file,
            title: &m.title,
            recipient: &m.recipient,
            occasion: &m.occasion,
            recorded_by: &m.recorded_by,
            note: &m.note,
            recorded_at: &m.recorded_at,
            duration_ms: m.duration_ms,
        });
    }

    let json = serde_json::to_string_pretty(&serde_json::json!({
        "format": "vocalkeep-legacy-messages",
        "version": 1,
        "speaker": bank.manifest.speaker.name,
        "exportedAt": crate::now_rfc3339(),
        "messages": entries,
    }))?;
    fs::write(out.join("messages.json"), json + "\n")?;

    let mut html = String::new();
    html.push_str(&format!(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n\
         <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n\
         <title>{title}</title>\n<style>\n{css}</style>\n</head>\n<body>\n<main>\n\
         <h1>{title}</h1>\n<p class=\"lede\">Recorded with Vocalkeep. Each message is an ordinary \
         WAV file in this folder, so it will open in any audio player.</p>\n",
        title = escape(&if name.is_empty() {
            "Legacy messages".to_string()
        } else {
            format!("Messages from {name}")
        }),
        css = LEGACY_CSS,
    ));
    for e in &entries {
        html.push_str("<article>\n");
        html.push_str(&format!("<h2>{}</h2>\n", escape(e.title)));
        let mut meta = Vec::new();
        if !e.recipient.is_empty() {
            meta.push(format!("For {}", escape(e.recipient)));
        }
        if !e.occasion.is_empty() {
            meta.push(escape(e.occasion));
        }
        if !e.recorded_by.is_empty() {
            meta.push(format!("Recorded by {}", escape(e.recorded_by)));
        }
        if let Some(date) = e.recorded_at.get(..10) {
            meta.push(escape(date));
        }
        html.push_str(&format!("<p class=\"meta\">{}</p>\n", meta.join(" · ")));
        if !e.note.is_empty() {
            html.push_str(&format!("<p>{}</p>\n", escape(e.note)));
        }
        html.push_str(&format!(
            "<audio controls preload=\"none\" src=\"{}\"></audio>\n</article>\n",
            escape(&url_path(&e.file))
        ));
    }
    if entries.is_empty() {
        html.push_str("<p>No messages yet.</p>\n");
    }
    html.push_str("</main>\n</body>\n</html>\n");
    fs::write(out.join("index.html"), html)?;
    fs::write(
        out.join("README.txt"),
        "Open index.html in a web browser to listen to every message, or play the WAV files \
         in any audio player.\nmessages.json lists the same details for other programs.\n",
    )?;

    Ok(ExportSummary {
        path: out.display().to_string(),
        files: entries.len(),
        bytes,
    })
}

const LEGACY_CSS: &str = "body{margin:0;font:18px/1.6 system-ui,sans-serif;background:#f6f3ee;\
color:#1f2a2b}main{max-width:44rem;margin:0 auto;padding:3rem 1.25rem}h1{font-weight:600;\
letter-spacing:-.01em}.lede{color:#4b5a5b}article{background:#fff;border-radius:16px;\
padding:1.25rem 1.5rem;margin:1rem 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}h2{margin:0 0 .25rem;\
font-size:1.2rem}.meta{margin:0 0 .75rem;color:#5b6b6c;font-size:.95rem}audio{width:100%}\
@media (prefers-color-scheme:dark){body{background:#151c1d;color:#e6eeee}article{background:\
#1f2829}.lede,.meta{color:#a9b8b9}}\n";

/// Removes characters that are not allowed in file names on Windows, macOS or Linux.
pub fn file_safe(s: &str) -> String {
    let cleaned: String = s
        .chars()
        .map(|c| match c {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => ' ',
            c if c.is_control() => ' ',
            c => c,
        })
        .collect();
    let cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    let cleaned = cleaned.trim_matches('.').trim().to_string();
    if cleaned.is_empty() {
        "Untitled".into()
    } else {
        cleaned
    }
}

fn truncate(s: &str, max_chars: usize) -> String {
    s.chars()
        .take(max_chars)
        .collect::<String>()
        .trim()
        .to_string()
}

fn unique_dir(base: &Path) -> PathBuf {
    if !base.exists() {
        return base.to_path_buf();
    }
    (2..)
        .map(|n| PathBuf::from(format!("{} ({n})", base.display())))
        .find(|p| !p.exists())
        .expect("a free folder name")
}

fn escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#39;")
}

/// Percent-encodes a file name for use in a relative URL.
fn url_path(name: &str) -> String {
    let mut out = String::new();
    for b in name.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bank::{LegacyDetails, Speaker};
    use crate::quality::{analyze, config};
    use crate::synth;

    fn bank_with_content(root: &Path) -> Bank {
        let mut bank = Bank::create(
            root,
            Speaker {
                name: "Jane <Doe>".into(),
                ..Default::default()
            },
        )
        .unwrap();
        let clip = synth::take(16_000, synth::Take::default());
        let a = analyze(&clip, None, config());
        let p = bank.prompt_ref("arctic_a0001").unwrap();
        bank.keep_take(&p, &clip, a, None).unwrap();
        bank.add_legacy(
            LegacyDetails {
                title: "Happy birthday, love".into(),
                recipient: "Mia".into(),
                occasion: "Birthday".into(),
                recorded_by: "Jane".into(),
                note: "For your 18th <3".into(),
            },
            &clip,
            None,
        )
        .unwrap();
        bank.save().unwrap();
        bank
    }

    #[test]
    fn backup_and_restore_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let bank = bank_with_content(&dir.path().join("bank"));
        let zip = dir.path().join("out").join("backup.zip");
        let summary = backup_zip(&bank, &zip).unwrap();
        assert_eq!(summary.files, 3);
        assert!(zip.exists());
        assert!(!zip.with_extension("zip.part").exists());

        let restored = restore_zip(&zip, &dir.path().join("restored")).unwrap();
        assert_eq!(restored.manifest.id, bank.manifest.id);
        assert_eq!(restored.manifest.takes.len(), 1);
        let take = &restored.manifest.takes[0];
        assert!(restored.resolve(&take.file).unwrap().exists());
        assert!(
            restore_zip(&zip, &dir.path().join("restored")).is_err(),
            "no overwrite"
        );
    }

    #[test]
    fn restore_rejects_other_zips() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("other.zip");
        let mut zip = ZipWriter::new(File::create(&path).unwrap());
        zip.start_file("hello.txt", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"hi").unwrap();
        zip.finish().unwrap();
        let err = restore_zip(&path, &dir.path().join("x")).err().unwrap();
        assert!(format!("{err:#}").contains("bank.json"));
    }

    #[test]
    fn legacy_export_is_playable_anywhere() {
        let dir = tempfile::tempdir().unwrap();
        let bank = bank_with_content(&dir.path().join("bank"));
        let out = dir.path().join("export");
        let summary = export_legacy(&bank, &out).unwrap();
        assert_eq!(summary.files, 1);
        let folder = PathBuf::from(&summary.path);
        assert!(
            folder.ends_with("Legacy messages from Jane Doe"),
            "{folder:?}"
        );
        let wav = folder.join("01 - Happy birthday, love (for Mia).wav");
        assert!(wav.exists());
        let html = fs::read_to_string(folder.join("index.html")).unwrap();
        assert!(html.contains("Messages from Jane &lt;Doe&gt;"));
        assert!(html.contains("For your 18th &lt;3"));
        assert!(html.contains("01%20-%20Happy%20birthday%2C%20love%20%28for%20Mia%29.wav"));
        let json: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(folder.join("messages.json")).unwrap())
                .unwrap();
        assert_eq!(json["messages"][0]["recipient"], "Mia");
        // A second export doesn't overwrite the first.
        let again = export_legacy(&bank, &out).unwrap();
        assert!(again.path.ends_with("(2)"), "{}", again.path);
    }

    #[test]
    fn file_names_are_safe() {
        assert_eq!(file_safe("a/b:c*d?"), "a b c d");
        assert_eq!(file_safe("..."), "Untitled");
        assert_eq!(file_safe("  Mum's  advice "), "Mum's advice");
    }
}
