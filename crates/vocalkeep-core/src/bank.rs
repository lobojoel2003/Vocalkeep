//! The voice bank: a plain folder of WAV files plus one `bank.json` describing them.
//!
//! ```text
//! My voice bank/
//!   bank.json                     what was said in each recording, quality, sessions, messages
//!   bank.json.bak                 the previous save, used if bank.json is ever damaged
//!   recordings/<set>/<prompt>.wav one take per prompt (16-bit PCM mono)
//!   legacy/<id>.wav               legacy messages
//!   pending/                      takes waiting to be kept or discarded (safe to delete)
//! ```
//!
//! The format is documented in `docs/voice-bank-format.md` and read by the training pipeline.
//! Everything stays on the person's computer; nothing here touches the network.

use std::collections::HashSet;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use crate::audio::{write_wav, Clip};
use crate::prompts::{CustomPrompt, Energy, PERSONAL_SET};
use crate::quality::{Analysis, Verdict};

pub const BANK_FORMAT: &str = "vocalkeep-bank";
pub const BANK_VERSION: u32 = 1;
pub const MANIFEST: &str = "bank.json";
const BACKUP: &str = "bank.json.bak";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Speaker {
    /// The name the voice will carry ("Jane's voice").
    pub name: String,
    /// BCP 47 language tag of the recordings, e.g. `en-US`.
    pub language: String,
    /// Used only to label the finished system voice (female, male or neutral).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gender: Option<String>,
}

impl Default for Speaker {
    fn default() -> Self {
        Self {
            name: String::new(),
            language: "en-US".into(),
            gender: None,
        }
    }
}

/// The kept recording of one prompt.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Take {
    pub prompt_id: String,
    pub set_id: String,
    /// Exactly what was read, so the bank stays meaningful if prompt sets change.
    pub text: String,
    /// Path relative to the bank folder, with `/` separators.
    pub file: String,
    pub sample_rate: u32,
    pub duration_ms: u32,
    pub recorded_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    /// How many times this prompt has been recorded (the latest take is kept).
    #[serde(default = "one")]
    pub attempts: u32,
    pub quality: Analysis,
}

fn one() -> u32 {
    1
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Session {
    pub id: String,
    pub started_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ended_at: Option<String>,
    pub energy: Energy,
    #[serde(default)]
    pub kept: u32,
    #[serde(default)]
    pub retried: u32,
    #[serde(default)]
    pub speech_ms: u64,
}

/// A recording kept exactly as it was said: a birthday wish, advice, a story, "I love you".
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyMessage {
    pub id: String,
    pub title: String,
    /// Who it is for ("Mia", "everyone").
    #[serde(default)]
    pub recipient: String,
    /// "Birthday", "Wedding day", "Just because"…
    #[serde(default)]
    pub occasion: String,
    /// Who is speaking. Family members can record messages too.
    #[serde(default)]
    pub recorded_by: String,
    #[serde(default)]
    pub note: String,
    pub file: String,
    pub sample_rate: u32,
    pub duration_ms: u32,
    pub recorded_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quality: Option<Analysis>,
}

/// Editable details of a legacy message.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct LegacyDetails {
    pub title: String,
    pub recipient: String,
    pub occasion: String,
    pub recorded_by: String,
    pub note: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Manifest {
    pub format: String,
    pub version: u32,
    pub id: String,
    pub created_at: String,
    pub updated_at: String,
    /// Version of Vocalkeep that last saved the bank.
    pub app_version: String,
    pub speaker: Speaker,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub room: Option<crate::quality::RoomCheck>,
    #[serde(default)]
    pub takes: Vec<Take>,
    #[serde(default)]
    pub sessions: Vec<Session>,
    #[serde(default)]
    pub custom_prompts: Vec<CustomPrompt>,
    #[serde(default)]
    pub legacy: Vec<LegacyMessage>,
}

impl Manifest {
    pub fn new(speaker: Speaker) -> Self {
        let now = crate::now_rfc3339();
        Self {
            format: BANK_FORMAT.into(),
            version: BANK_VERSION,
            id: uuid::Uuid::new_v4().to_string(),
            created_at: now.clone(),
            updated_at: now,
            app_version: crate::build_info::VERSION.into(),
            speaker,
            room: None,
            takes: Vec::new(),
            sessions: Vec::new(),
            custom_prompts: Vec::new(),
            legacy: Vec::new(),
        }
    }
}

/// What a take is of: a prompt from a set, or one of the person's own phrases.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRef {
    pub id: String,
    pub set_id: String,
    pub text: String,
}

pub struct Bank {
    root: PathBuf,
    pub manifest: Manifest,
}

impl Bank {
    /// Creates a new, empty bank in `root` (which may already exist but must not hold a bank).
    pub fn create(root: &Path, speaker: Speaker) -> Result<Self> {
        if root.join(MANIFEST).exists() {
            bail!("{} already holds a voice bank", root.display());
        }
        fs::create_dir_all(root).with_context(|| format!("creating {}", root.display()))?;
        let bank = Self {
            root: root.to_path_buf(),
            manifest: Manifest::new(speaker),
        };
        bank.save()?;
        Ok(bank)
    }

    /// Opens a bank, falling back to the recovery copy if `bank.json` is damaged.
    pub fn open(root: &Path) -> Result<Self> {
        let primary = root.join(MANIFEST);
        let manifest = match read_manifest(&primary) {
            Ok(m) => m,
            Err(e) => {
                let backup = root.join(BACKUP);
                if backup.exists() {
                    log::warn!("{}: {e:#}; using the recovery copy", primary.display());
                    read_manifest(&backup).with_context(|| {
                        format!("{} and its recovery copy are damaged", primary.display())
                    })?
                } else {
                    return Err(e);
                }
            }
        };
        Ok(Self {
            root: root.to_path_buf(),
            manifest,
        })
    }

    pub fn open_or_create(root: &Path, speaker: Speaker) -> Result<Self> {
        if root.join(MANIFEST).exists() || root.join(BACKUP).exists() {
            Self::open(root)
        } else {
            Self::create(root, speaker)
        }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Saves `bank.json` atomically: write a temporary file, keep the previous save as the
    /// recovery copy, then move the new file into place.
    pub fn save(&self) -> Result<()> {
        let mut manifest = self.manifest.clone();
        manifest.updated_at = crate::now_rfc3339();
        manifest.app_version = crate::build_info::VERSION.into();
        let json = serde_json::to_vec_pretty(&manifest)?;
        let tmp = self.root.join("bank.json.tmp");
        {
            let mut f =
                fs::File::create(&tmp).with_context(|| format!("writing {}", tmp.display()))?;
            f.write_all(&json)?;
            f.write_all(b"\n")?;
            f.sync_all()?;
        }
        let primary = self.root.join(MANIFEST);
        if primary.exists() {
            fs::copy(&primary, self.root.join(BACKUP)).context("keeping a recovery copy")?;
        }
        fs::rename(&tmp, &primary).with_context(|| format!("saving {}", primary.display()))?;
        Ok(())
    }

    /// Absolute path of a file named in the manifest. Refuses paths that leave the bank.
    pub fn resolve(&self, relative: &str) -> Result<PathBuf> {
        let rel = Path::new(relative);
        if rel.is_absolute()
            || rel
                .components()
                .any(|c| !matches!(c, std::path::Component::Normal(_)))
        {
            bail!("unsafe path in voice bank: {relative}");
        }
        Ok(self.root.join(rel))
    }

    // ----- Sessions -----

    pub fn start_session(&mut self, energy: Energy) -> String {
        let id = uuid::Uuid::new_v4().to_string();
        self.manifest.sessions.push(Session {
            id: id.clone(),
            started_at: crate::now_rfc3339(),
            ended_at: None,
            energy,
            kept: 0,
            retried: 0,
            speech_ms: 0,
        });
        id
    }

    pub fn end_session(&mut self, id: &str) {
        if let Some(s) = self.session_mut(id) {
            s.ended_at = Some(crate::now_rfc3339());
        }
        // Sessions where nothing was kept are not worth remembering.
        self.manifest
            .sessions
            .retain(|s| s.id != id || s.kept > 0 || s.retried > 0);
    }

    pub fn note_retry(&mut self, session_id: &str) {
        if let Some(s) = self.session_mut(session_id) {
            s.retried += 1;
        }
    }

    fn session_mut(&mut self, id: &str) -> Option<&mut Session> {
        self.manifest.sessions.iter_mut().find(|s| s.id == id)
    }

    // ----- Takes -----

    /// Keeps a take for a prompt, replacing any earlier one.
    pub fn keep_take(
        &mut self,
        prompt: &PromptRef,
        clip: &Clip,
        quality: Analysis,
        session_id: Option<&str>,
    ) -> Result<Take> {
        let file = take_file(prompt);
        write_wav(&self.resolve(&file)?, clip)?;
        Ok(self.record_take(
            prompt,
            file,
            clip.sample_rate,
            clip.duration_ms(),
            quality,
            session_id,
        ))
    }

    /// Keeps a take that is already a WAV file (for example a pending take), moving it into
    /// the bank.
    pub fn keep_take_file(
        &mut self,
        prompt: &PromptRef,
        source: &Path,
        quality: Analysis,
        session_id: Option<&str>,
    ) -> Result<Take> {
        let file = take_file(prompt);
        let (rate, ms) = adopt_wav(source, &self.resolve(&file)?)?;
        Ok(self.record_take(prompt, file, rate, ms, quality, session_id))
    }

    fn record_take(
        &mut self,
        prompt: &PromptRef,
        file: String,
        sample_rate: u32,
        duration_ms: u32,
        quality: Analysis,
        session_id: Option<&str>,
    ) -> Take {
        let attempts = self
            .manifest
            .takes
            .iter()
            .find(|t| t.prompt_id == prompt.id)
            .map(|t| t.attempts + 1)
            .unwrap_or(1);
        self.manifest.takes.retain(|t| t.prompt_id != prompt.id);
        let take = Take {
            prompt_id: prompt.id.clone(),
            set_id: prompt.set_id.clone(),
            text: prompt.text.clone(),
            file,
            sample_rate,
            duration_ms,
            recorded_at: crate::now_rfc3339(),
            session_id: session_id.map(str::to_string),
            attempts,
            quality,
        };
        if let Some(s) = session_id.and_then(|id| self.session_mut(id)) {
            s.kept += 1;
            s.speech_ms += take.quality.speech_ms as u64;
        }
        self.manifest.takes.push(take.clone());
        take
    }

    pub fn take(&self, prompt_id: &str) -> Option<&Take> {
        self.manifest
            .takes
            .iter()
            .find(|t| t.prompt_id == prompt_id)
    }

    pub fn remove_take(&mut self, prompt_id: &str) -> Result<bool> {
        let Some(take) = self.take(prompt_id).cloned() else {
            return Ok(false);
        };
        let path = self.resolve(&take.file)?;
        if path.exists() {
            fs::remove_file(&path).with_context(|| format!("deleting {}", path.display()))?;
        }
        self.manifest.takes.retain(|t| t.prompt_id != prompt_id);
        Ok(true)
    }

    /// Prompts that don't need recording again (kept takes that weren't marked "redo").
    pub fn done_ids(&self) -> HashSet<String> {
        self.manifest
            .takes
            .iter()
            .filter(|t| t.quality.verdict != Verdict::Redo)
            .map(|t| t.prompt_id.clone())
            .collect()
    }

    // ----- The person's own phrases -----

    pub fn add_custom_prompt(&mut self, text: &str) -> Result<CustomPrompt> {
        let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
        if text.is_empty() {
            bail!("the phrase is empty");
        }
        if text.chars().count() > 300 {
            bail!("phrases can be up to 300 characters");
        }
        if self
            .manifest
            .custom_prompts
            .iter()
            .any(|c| c.text.eq_ignore_ascii_case(&text))
        {
            bail!("that phrase is already in the list");
        }
        let next = self
            .manifest
            .custom_prompts
            .iter()
            .filter_map(|c| c.id.strip_prefix("personal-")?.parse::<u32>().ok())
            .max()
            .unwrap_or(0)
            + 1;
        let prompt = CustomPrompt {
            id: format!("personal-{next:04}"),
            text,
            created_at: crate::now_rfc3339(),
        };
        self.manifest.custom_prompts.push(prompt.clone());
        Ok(prompt)
    }

    pub fn remove_custom_prompt(&mut self, id: &str) -> Result<()> {
        self.remove_take(id)?;
        self.manifest.custom_prompts.retain(|c| c.id != id);
        Ok(())
    }

    /// Looks up a prompt by id among the built-in sets and the person's own phrases.
    pub fn prompt_ref(&self, prompt_id: &str) -> Option<PromptRef> {
        if let Some((set, p)) = crate::prompts::library().get(prompt_id) {
            return Some(PromptRef {
                id: p.id.clone(),
                set_id: set.id.clone(),
                text: p.text.clone(),
            });
        }
        self.manifest
            .custom_prompts
            .iter()
            .find(|c| c.id == prompt_id)
            .map(|c| PromptRef {
                id: c.id.clone(),
                set_id: PERSONAL_SET.into(),
                text: c.text.clone(),
            })
    }

    // ----- Legacy messages -----

    pub fn add_legacy(
        &mut self,
        details: LegacyDetails,
        clip: &Clip,
        quality: Option<Analysis>,
    ) -> Result<LegacyMessage> {
        let id = uuid::Uuid::new_v4().to_string();
        let file = format!("legacy/{id}.wav");
        write_wav(&self.resolve(&file)?, clip)?;
        Ok(self.record_legacy(
            id,
            file,
            details,
            clip.sample_rate,
            clip.duration_ms(),
            quality,
        ))
    }

    /// Adds a legacy message from a WAV file, moving it into the bank.
    pub fn add_legacy_file(
        &mut self,
        details: LegacyDetails,
        source: &Path,
        quality: Option<Analysis>,
    ) -> Result<LegacyMessage> {
        let id = uuid::Uuid::new_v4().to_string();
        let file = format!("legacy/{id}.wav");
        let (rate, ms) = adopt_wav(source, &self.resolve(&file)?)?;
        Ok(self.record_legacy(id, file, details, rate, ms, quality))
    }

    fn record_legacy(
        &mut self,
        id: String,
        file: String,
        details: LegacyDetails,
        sample_rate: u32,
        duration_ms: u32,
        quality: Option<Analysis>,
    ) -> LegacyMessage {
        let message = LegacyMessage {
            id,
            title: clean_title(&details.title, "A message"),
            recipient: details.recipient.trim().to_string(),
            occasion: details.occasion.trim().to_string(),
            recorded_by: details.recorded_by.trim().to_string(),
            note: details.note.trim().to_string(),
            file,
            sample_rate,
            duration_ms,
            recorded_at: crate::now_rfc3339(),
            quality,
        };
        self.manifest.legacy.push(message.clone());
        message
    }

    pub fn update_legacy(&mut self, id: &str, details: LegacyDetails) -> Result<LegacyMessage> {
        let m = self
            .manifest
            .legacy
            .iter_mut()
            .find(|m| m.id == id)
            .ok_or_else(|| anyhow!("that message no longer exists"))?;
        m.title = clean_title(&details.title, &m.title.clone());
        m.recipient = details.recipient.trim().to_string();
        m.occasion = details.occasion.trim().to_string();
        m.recorded_by = details.recorded_by.trim().to_string();
        m.note = details.note.trim().to_string();
        Ok(m.clone())
    }

    pub fn legacy(&self, id: &str) -> Option<&LegacyMessage> {
        self.manifest.legacy.iter().find(|m| m.id == id)
    }

    pub fn remove_legacy(&mut self, id: &str) -> Result<()> {
        if let Some(m) = self.legacy(id).cloned() {
            let path = self.resolve(&m.file)?;
            if path.exists() {
                fs::remove_file(&path)?;
            }
        }
        self.manifest.legacy.retain(|m| m.id != id);
        Ok(())
    }

    // ----- Pending takes -----

    /// Where an unconfirmed take is kept until the person keeps or discards it.
    pub fn pending_path(&self, token: &str) -> Result<PathBuf> {
        if token.is_empty() || !token.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') {
            bail!("invalid take id");
        }
        Ok(self.root.join("pending").join(format!("{token}.wav")))
    }

    /// Deletes takes that were never kept (for example after a crash).
    pub fn clear_pending(&self) -> Result<()> {
        let dir = self.root.join("pending");
        if dir.exists() {
            fs::remove_dir_all(&dir).with_context(|| format!("clearing {}", dir.display()))?;
        }
        Ok(())
    }
}

fn take_file(prompt: &PromptRef) -> String {
    format!(
        "recordings/{}/{}.wav",
        safe_name(&prompt.set_id),
        safe_name(&prompt.id)
    )
}

/// Moves a WAV file to `dest` (copying across drives) and returns its sample rate and length.
fn adopt_wav(source: &Path, dest: &Path) -> Result<(u32, u32)> {
    let reader =
        hound::WavReader::open(source).with_context(|| format!("reading {}", source.display()))?;
    let spec = reader.spec();
    let frames = reader.duration() as u64;
    drop(reader);
    if spec.sample_rate == 0 {
        bail!("{} has no sample rate", source.display());
    }
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent)?;
    }
    if fs::rename(source, dest).is_err() {
        fs::copy(source, dest).with_context(|| format!("saving {}", dest.display()))?;
        let _ = fs::remove_file(source);
    }
    Ok((
        spec.sample_rate,
        (frames * 1000 / spec.sample_rate as u64) as u32,
    ))
}

fn read_manifest(path: &Path) -> Result<Manifest> {
    let bytes = fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    let manifest: Manifest = serde_json::from_slice(&bytes)
        .with_context(|| format!("{} is not a valid voice bank", path.display()))?;
    if manifest.format != BANK_FORMAT {
        bail!("{} is not a Vocalkeep voice bank", path.display());
    }
    if manifest.version > BANK_VERSION {
        bail!(
            "this voice bank was saved by a newer Vocalkeep (format {}); please update",
            manifest.version
        );
    }
    Ok(manifest)
}

/// A file-name-safe version of an id: letters, digits, `-` and `_` only.
pub fn safe_name(id: &str) -> String {
    let s: String = id
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    if s.is_empty() {
        "_".into()
    } else {
        s
    }
}

fn clean_title(title: &str, fallback: &str) -> String {
    let t = title.split_whitespace().collect::<Vec<_>>().join(" ");
    let t: String = t.chars().take(120).collect();
    if t.is_empty() {
        fallback.to_string()
    } else {
        t
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::quality::{analyze, config};
    use crate::synth;

    fn speaker() -> Speaker {
        Speaker {
            name: "Jane".into(),
            language: "en-US".into(),
            gender: Some("female".into()),
        }
    }

    fn take_clip() -> (Clip, Analysis) {
        let clip = synth::take(16_000, synth::Take::default());
        let a = analyze(&clip, None, config());
        (clip, a)
    }

    #[test]
    fn create_save_and_reopen() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("bank");
        let mut bank = Bank::create(&root, speaker()).unwrap();
        assert!(Bank::create(&root, speaker()).is_err(), "no overwriting");
        let session = bank.start_session(Energy::Okay);
        let (clip, a) = take_clip();
        let prompt = bank.prompt_ref("arctic_a0001").unwrap();
        let take = bank.keep_take(&prompt, &clip, a, Some(&session)).unwrap();
        assert_eq!(take.file, "recordings/arctic-en/arctic_a0001.wav");
        assert!(root.join(&take.file).exists());
        bank.end_session(&session);
        bank.save().unwrap();

        let reopened = Bank::open(&root).unwrap();
        assert_eq!(reopened.manifest.speaker.name, "Jane");
        assert_eq!(reopened.manifest.takes.len(), 1);
        assert_eq!(reopened.manifest.sessions[0].kept, 1);
        assert!(reopened.done_ids().contains("arctic_a0001"));
    }

    #[test]
    fn retaking_replaces_and_counts_attempts() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        let (clip, a) = take_clip();
        let prompt = bank.prompt_ref("arctic_a0002").unwrap();
        bank.keep_take(&prompt, &clip, a.clone(), None).unwrap();
        let second = bank.keep_take(&prompt, &clip, a, None).unwrap();
        assert_eq!(second.attempts, 2);
        assert_eq!(bank.manifest.takes.len(), 1);
        assert!(bank.remove_take("arctic_a0002").unwrap());
        assert!(!dir.path().join(&second.file).exists());
        assert!(!bank.remove_take("arctic_a0002").unwrap());
    }

    #[test]
    fn redo_takes_are_not_done() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        let clip = Clip::new(16_000, synth::noise(16_000, 1.0, -80.0, 1));
        let a = analyze(&clip, None, config());
        assert_eq!(a.verdict, Verdict::Redo);
        let prompt = bank.prompt_ref("arctic_a0003").unwrap();
        bank.keep_take(&prompt, &clip, a, None).unwrap();
        assert!(bank.done_ids().is_empty());
    }

    #[test]
    fn damaged_manifest_falls_back_to_recovery_copy() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        bank.manifest.speaker.name = "Jane Doe".into();
        bank.save().unwrap(); // the first save becomes bank.json.bak
        fs::write(dir.path().join(MANIFEST), b"{ not json").unwrap();
        let reopened = Bank::open(dir.path()).unwrap();
        assert_eq!(reopened.manifest.speaker.name, "Jane");
    }

    #[test]
    fn rejects_other_files_and_newer_formats() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join(MANIFEST), br#"{"format":"other"}"#).unwrap();
        assert!(Bank::open(dir.path()).is_err());
        let mut m = Manifest::new(speaker());
        m.version = BANK_VERSION + 1;
        fs::write(dir.path().join(MANIFEST), serde_json::to_vec(&m).unwrap()).unwrap();
        let err = Bank::open(dir.path()).err().unwrap();
        assert!(format!("{err:#}").contains("newer"), "{err:#}");
    }

    #[test]
    fn personal_phrases() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        let p = bank.add_custom_prompt("  Biscuit,   come here! ").unwrap();
        assert_eq!(p.id, "personal-0001");
        assert_eq!(p.text, "Biscuit, come here!");
        assert!(bank.add_custom_prompt("biscuit, come here!").is_err());
        assert!(bank.add_custom_prompt("   ").is_err());
        let p2 = bank.add_custom_prompt("Hello, Priya.").unwrap();
        assert_eq!(p2.id, "personal-0002");
        let r = bank.prompt_ref(&p2.id).unwrap();
        assert_eq!(r.set_id, PERSONAL_SET);
        let (clip, a) = take_clip();
        let take = bank.keep_take(&r, &clip, a, None).unwrap();
        assert_eq!(take.file, "recordings/personal/personal-0002.wav");
        bank.remove_custom_prompt(&p2.id).unwrap();
        assert!(bank.take(&p2.id).is_none());
        assert!(bank.prompt_ref(&p2.id).is_none());
    }

    #[test]
    fn legacy_messages() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        let (clip, _) = take_clip();
        let m = bank
            .add_legacy(
                LegacyDetails {
                    title: "  Happy   birthday ".into(),
                    recipient: "Mia".into(),
                    occasion: "Birthday".into(),
                    recorded_by: "Mum".into(),
                    note: String::new(),
                },
                &clip,
                None,
            )
            .unwrap();
        assert_eq!(m.title, "Happy birthday");
        assert!(dir.path().join(&m.file).exists());
        let updated = bank
            .update_legacy(
                &m.id,
                LegacyDetails {
                    title: String::new(),
                    recipient: "Mia and Leo".into(),
                    ..Default::default()
                },
            )
            .unwrap();
        assert_eq!(
            updated.title, "Happy birthday",
            "empty title keeps the old one"
        );
        assert_eq!(updated.recipient, "Mia and Leo");
        bank.remove_legacy(&m.id).unwrap();
        assert!(bank.manifest.legacy.is_empty());
        assert!(!dir.path().join(&m.file).exists());
    }

    #[test]
    fn unsafe_paths_are_refused() {
        let dir = tempfile::tempdir().unwrap();
        let bank = Bank::create(dir.path(), speaker()).unwrap();
        assert!(bank.resolve("../outside.wav").is_err());
        assert!(bank.resolve("/etc/passwd").is_err());
        assert!(bank.resolve("recordings/a/b.wav").is_ok());
        assert!(bank.pending_path("../../x").is_err());
        assert!(bank.pending_path("abc-123").is_ok());
        assert_eq!(safe_name("a/b\\c..d"), "a_b_c__d");
    }

    #[test]
    fn pending_files_are_adopted() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        let (clip, a) = take_clip();
        let pending = bank.pending_path("tok-1").unwrap();
        write_wav(&pending, &clip).unwrap();
        let prompt = bank.prompt_ref("phrases-0001").unwrap();
        let take = bank.keep_take_file(&prompt, &pending, a, None).unwrap();
        assert!(!pending.exists(), "moved, not copied");
        assert!(dir.path().join(&take.file).exists());
        assert_eq!(take.sample_rate, 16_000);
        assert_eq!(take.duration_ms, clip.duration_ms());

        let pending = bank.pending_path("tok-2").unwrap();
        write_wav(&pending, &clip).unwrap();
        let m = bank
            .add_legacy_file(LegacyDetails::default(), &pending, None)
            .unwrap();
        assert_eq!(m.title, "A message");
        assert_eq!(m.duration_ms, clip.duration_ms());
        assert!(dir.path().join(&m.file).exists());
    }

    #[test]
    fn empty_sessions_are_forgotten() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), speaker()).unwrap();
        let s = bank.start_session(Energy::Tired);
        bank.end_session(&s);
        assert!(bank.manifest.sessions.is_empty());
    }
}
