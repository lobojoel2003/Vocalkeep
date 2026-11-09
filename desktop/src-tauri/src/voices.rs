//! Voices built by the pipeline: folders with `<id>.onnx`, `<id>.onnx.json`, `MODEL_CARD` and
//! `voice.json` (see `docs/voice-format.md`).

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct BaseInfo {
    pub id: String,
    pub license: String,
    pub commercial: String,
    pub lineage: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct BankInfo {
    pub id: String,
    pub takes: u64,
    pub minutes: f64,
}

/// What the app shows for a voice. Unknown fields in `voice.json` are ignored.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct VoiceInfo {
    pub id: String,
    pub name: String,
    pub language: String,
    pub gender: Option<String>,
    pub sample_rate: u32,
    pub base: BaseInfo,
    pub bank: BankInfo,
    pub created_at: String,
    pub vocalkeep_version: String,
    /// Filled in by the app.
    pub path: String,
    pub size_bytes: u64,
    pub model_card: Option<String>,
}

/// A voice id is a folder name: letters, digits, `_` and `-` only.
pub fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 120
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

pub fn list(dir: &Path) -> Vec<VoiceInfo> {
    let Ok(entries) = fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut voices: Vec<VoiceInfo> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .filter_map(|e| read(&e.path()))
        .collect();
    voices.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    voices
}

fn read(folder: &Path) -> Option<VoiceInfo> {
    let id = folder.file_name()?.to_str()?.to_string();
    if !valid_id(&id) {
        return None;
    }
    let onnx = folder.join(format!("{id}.onnx"));
    if !onnx.is_file() {
        return None;
    }
    let mut info: VoiceInfo = fs::read(folder.join("voice.json"))
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    info.id = id.clone();
    if info.name.is_empty() {
        info.name = id.clone();
    }
    info.path = folder.display().to_string();
    info.size_bytes = fs::metadata(&onnx).map(|m| m.len()).unwrap_or(0);
    info.model_card = fs::read_to_string(folder.join("MODEL_CARD")).ok();
    Some(info)
}

pub fn folder(dir: &Path, id: &str) -> Result<PathBuf> {
    if !valid_id(id) {
        bail!("That isn't a valid voice.");
    }
    let path = dir.join(id);
    if !path.join(format!("{id}.onnx")).is_file() {
        bail!("That voice is no longer on this computer.");
    }
    Ok(path)
}

pub fn delete(dir: &Path, id: &str) -> Result<()> {
    let path = folder(dir, id)?;
    fs::remove_dir_all(&path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lists_voice_folders() {
        let dir = tempfile::tempdir().unwrap();
        let v = dir.path().join("en_US-jane-medium");
        fs::create_dir_all(&v).unwrap();
        fs::write(v.join("en_US-jane-medium.onnx"), b"onnx").unwrap();
        fs::write(
            v.join("voice.json"),
            br#"{"format":"vocalkeep-voice","name":"Jane","language":"en-US","base":{"id":"en_US-ljspeech-medium","license":"Public domain","commercial":"yes"},"bank":{"takes":640,"minutes":41.5},"createdAt":"2026-11-01T10:00:00Z","extra":true}"#,
        )
        .unwrap();
        fs::write(v.join("MODEL_CARD"), "Jane's voice").unwrap();
        // Not voices:
        fs::create_dir_all(dir.path().join("empty")).unwrap();
        fs::create_dir_all(dir.path().join("bad name!")).unwrap();

        let voices = list(dir.path());
        assert_eq!(voices.len(), 1);
        let jane = &voices[0];
        assert_eq!(jane.id, "en_US-jane-medium");
        assert_eq!(jane.name, "Jane");
        assert_eq!(jane.bank.takes, 640);
        assert_eq!(jane.base.commercial, "yes");
        assert_eq!(jane.size_bytes, 4);
        assert_eq!(jane.model_card.as_deref(), Some("Jane's voice"));
        assert!(folder(dir.path(), "../etc").is_err());
        delete(dir.path(), "en_US-jane-medium").unwrap();
        assert!(list(dir.path()).is_empty());
    }
}
