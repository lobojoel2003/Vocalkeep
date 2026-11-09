//! App preferences, saved as JSON in the app's config folder.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use vocalkeep_core::prompts::Energy;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum Theme {
    #[default]
    System,
    Light,
    Dark,
    Contrast,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum TextSize {
    #[default]
    Normal,
    Large,
    Larger,
    Largest,
}

/// How long a session is on each kind of day.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionLength {
    pub minutes: u32,
    pub prompts: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionLengths {
    pub strong: SessionLength,
    pub okay: SessionLength,
    pub tired: SessionLength,
}

impl Default for SessionLengths {
    fn default() -> Self {
        Self {
            strong: SessionLength {
                minutes: 20,
                prompts: 40,
            },
            okay: SessionLength {
                minutes: 12,
                prompts: 25,
            },
            tired: SessionLength {
                minutes: 5,
                prompts: 10,
            },
        }
    }
}

impl SessionLengths {
    pub fn for_energy(&self, energy: Energy) -> &SessionLength {
        match energy {
            Energy::Strong => &self.strong,
            Energy::Okay => &self.okay,
            Energy::Tired => &self.tired,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Settings {
    pub theme: Theme,
    pub text_size: TextSize,
    pub reduce_motion: bool,
    /// Microphone id from the device list; `None` uses the system default.
    pub input_device: Option<String>,
    pub sessions: SessionLengths,
    /// Suggest a sip of water after this many kept sentences (0 turns it off).
    pub break_every: u32,
    /// Play each take back as soon as it is recorded.
    pub auto_play: bool,
    /// Keep takes that pass every check and move on without a click.
    pub auto_keep_good: bool,
    /// Prompt sets to draw from; empty means all of them.
    pub enabled_sets: Vec<String>,
    /// Where the voice bank lives; `None` uses the app's data folder.
    pub bank_dir: Option<String>,
    /// How to run the training pipeline, e.g. `/home/me/.venv/bin/vocalkeep`.
    pub pipeline_command: Option<String>,
    pub onboarded: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            theme: Theme::System,
            text_size: TextSize::Normal,
            reduce_motion: false,
            input_device: None,
            sessions: SessionLengths::default(),
            break_every: 10,
            auto_play: false,
            auto_keep_good: false,
            enabled_sets: Vec::new(),
            bank_dir: None,
            pipeline_command: None,
            onboarded: false,
        }
    }
}

impl Settings {
    /// Keeps values within sensible bounds whatever the file or the UI says.
    pub fn sanitized(mut self) -> Self {
        for len in [
            &mut self.sessions.strong,
            &mut self.sessions.okay,
            &mut self.sessions.tired,
        ] {
            len.minutes = len.minutes.clamp(1, 90);
            len.prompts = len.prompts.clamp(1, 200);
        }
        self.break_every = self.break_every.min(100);
        self.input_device = self.input_device.filter(|d| !d.trim().is_empty());
        self.bank_dir = self.bank_dir.filter(|d| !d.trim().is_empty());
        self.pipeline_command = self
            .pipeline_command
            .map(|c| c.trim().to_string())
            .filter(|c| !c.is_empty());
        self.enabled_sets.sort();
        self.enabled_sets.dedup();
        self
    }
}

pub fn settings_path(config_dir: &Path) -> PathBuf {
    config_dir.join("settings.json")
}

/// Loads settings; a missing or damaged file gives the defaults.
pub fn load(config_dir: &Path) -> Settings {
    let path = settings_path(config_dir);
    match fs::read(&path) {
        Ok(bytes) => serde_json::from_slice::<Settings>(&bytes)
            .map(Settings::sanitized)
            .unwrap_or_else(|e| {
                log::warn!("{}: {e}; using default settings", path.display());
                Settings::default()
            }),
        Err(_) => Settings::default(),
    }
}

pub fn save(config_dir: &Path, settings: &Settings) -> Result<()> {
    fs::create_dir_all(config_dir).with_context(|| format!("creating {}", config_dir.display()))?;
    let path = settings_path(config_dir);
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, serde_json::to_vec_pretty(settings)?)?;
    fs::rename(&tmp, &path).with_context(|| format!("saving {}", path.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_defaults() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(load(dir.path()), Settings::default());
        let s = Settings {
            theme: Theme::Contrast,
            auto_play: true,
            ..Default::default()
        };
        save(dir.path(), &s).unwrap();
        assert_eq!(load(dir.path()), s);
    }

    #[test]
    fn damaged_file_gives_defaults() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(settings_path(dir.path()), b"{oops").unwrap();
        assert_eq!(load(dir.path()), Settings::default());
    }

    #[test]
    fn unknown_and_missing_fields_are_tolerated() {
        let s: Settings = serde_json::from_str(r#"{"theme":"dark","future":1}"#).unwrap();
        assert_eq!(s.theme, Theme::Dark);
        assert_eq!(s.break_every, 10);
    }

    #[test]
    fn sanitize_clamps() {
        let mut s = Settings::default();
        s.sessions.tired.minutes = 0;
        s.sessions.strong.prompts = 10_000;
        s.pipeline_command = Some("  ".into());
        let s = s.sanitized();
        assert_eq!(s.sessions.tired.minutes, 1);
        assert_eq!(s.sessions.strong.prompts, 200);
        assert_eq!(s.pipeline_command, None);
    }
}
