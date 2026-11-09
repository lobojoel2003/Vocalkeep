//! How far the voice bank has come: milestones, sounds covered and time spoken.
//!
//! Milestones count kept sentences. Piper does not publish a minimum dataset size; voices have
//! been fine-tuned from about an hour of speech. The thresholds below are Vocalkeep's guidance,
//! explained in `docs/training.md`.

use std::collections::{BTreeSet, HashMap};

use serde::Serialize;

use crate::bank::Manifest;
use crate::prompts::{Inventory, Library, PERSONAL_SET};
use crate::quality::Verdict;

/// A step on the way to a full voice. The app shows a title and a sentence for each id.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Milestone {
    pub id: &'static str,
    /// Kept sentences needed.
    pub at: usize,
}

pub const MILESTONES: &[Milestone] = &[
    Milestone {
        id: "first-words",
        at: 10,
    },
    Milestone {
        id: "preview",
        at: 100,
    },
    Milestone {
        id: "recognisable",
        at: 300,
    },
    Milestone {
        id: "natural",
        at: 600,
    },
    Milestone {
        id: "rich",
        at: 1000,
    },
    Milestone {
        id: "complete",
        at: 1500,
    },
];

/// Kept sentences needed before Vocalkeep suggests building a voice for everyday use.
pub const RECOMMENDED_TAKES: usize = 600;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SetProgress {
    pub id: String,
    pub title: String,
    pub recorded: usize,
    pub total: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    /// Takes ready for training (good or okay).
    pub kept: usize,
    pub good: usize,
    pub okay: usize,
    /// Takes kept even though a redo was suggested.
    pub needs_redo: usize,
    pub total_prompts: usize,
    pub speech_minutes: f32,
    pub phonemes_covered: usize,
    pub phonemes_total: usize,
    pub diphones_covered: usize,
    pub diphones_total: usize,
    pub milestone: Option<Milestone>,
    pub next_milestone: Option<Milestone>,
    /// 0..1 progress from the current milestone to the next.
    pub to_next: f32,
    pub recommended: usize,
    pub sets: Vec<SetProgress>,
    pub sessions: usize,
    /// Distinct days with at least one session (no streaks: rest days are good days).
    pub days_recorded: usize,
    pub last_session_at: Option<String>,
    pub legacy_messages: usize,
    pub legacy_minutes: f32,
    /// Recent kept takes per day, oldest first, for a small chart.
    pub recent_days: Vec<DayCount>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DayCount {
    pub date: String,
    pub kept: usize,
}

pub fn progress(manifest: &Manifest, library: &Library) -> Progress {
    let mut good = 0;
    let mut okay = 0;
    let mut needs_redo = 0;
    let mut speech_ms: u64 = 0;
    let mut covered = Inventory::default();
    let mut per_set: HashMap<&str, usize> = HashMap::new();
    let mut per_day: HashMap<String, usize> = HashMap::new();

    for take in &manifest.takes {
        match take.quality.verdict {
            Verdict::Good => good += 1,
            Verdict::Okay => okay += 1,
            Verdict::Redo => {
                needs_redo += 1;
                continue;
            }
        }
        speech_ms += take.quality.speech_ms as u64;
        *per_set.entry(take.set_id.as_str()).or_default() += 1;
        if let Some((_, prompt)) = library.get(&take.prompt_id) {
            if let Some(ph) = &prompt.ph {
                covered.add(ph);
            }
        }
        if let Some(day) = local_day(&take.recorded_at) {
            *per_day.entry(day).or_default() += 1;
        }
    }

    let kept = good + okay;
    let milestone = MILESTONES.iter().rev().find(|m| kept >= m.at).copied();
    let next_milestone = MILESTONES.iter().find(|m| kept < m.at).copied();
    let to_next = match next_milestone {
        Some(next) => {
            let from = milestone.map(|m| m.at).unwrap_or(0);
            ((kept - from) as f32 / (next.at - from).max(1) as f32).clamp(0.0, 1.0)
        }
        None => 1.0,
    };

    let mut sets: Vec<SetProgress> = library
        .sets()
        .map(|s| SetProgress {
            id: s.id.clone(),
            title: s.title.clone(),
            recorded: per_set.get(s.id.as_str()).copied().unwrap_or(0),
            total: s.prompts.len(),
        })
        .collect();
    if !manifest.custom_prompts.is_empty() {
        sets.push(SetProgress {
            id: PERSONAL_SET.into(),
            title: "Your own phrases".into(),
            recorded: per_set.get(PERSONAL_SET).copied().unwrap_or(0),
            total: manifest.custom_prompts.len(),
        });
    }

    let inventory = library.inventory();
    let days: BTreeSet<String> = manifest
        .sessions
        .iter()
        .filter_map(|s| local_day(&s.started_at))
        .chain(per_day.keys().cloned())
        .collect();

    let mut recent: Vec<DayCount> = per_day
        .into_iter()
        .map(|(date, kept)| DayCount { date, kept })
        .collect();
    recent.sort_by(|a, b| a.date.cmp(&b.date));
    let recent_days = recent.split_off(recent.len().saturating_sub(14));

    Progress {
        kept,
        good,
        okay,
        needs_redo,
        total_prompts: library.total() + manifest.custom_prompts.len(),
        speech_minutes: speech_ms as f32 / 60_000.0,
        phonemes_covered: covered.phonemes.intersection(&inventory.phonemes).count(),
        phonemes_total: inventory.phonemes.len(),
        diphones_covered: covered.diphones.intersection(&inventory.diphones).count(),
        diphones_total: inventory.diphones.len(),
        milestone,
        next_milestone,
        to_next,
        recommended: RECOMMENDED_TAKES,
        sets,
        sessions: manifest.sessions.len(),
        days_recorded: days.len(),
        last_session_at: manifest.sessions.iter().map(|s| s.started_at.clone()).max(),
        legacy_messages: manifest.legacy.len(),
        legacy_minutes: manifest
            .legacy
            .iter()
            .map(|m| m.duration_ms as f32)
            .sum::<f32>()
            / 60_000.0,
        recent_days,
    }
}

/// The local calendar day (YYYY-MM-DD) of an RFC 3339 timestamp.
fn local_day(ts: &str) -> Option<String> {
    chrono::DateTime::parse_from_rfc3339(ts).ok().map(|t| {
        t.with_timezone(&chrono::Local)
            .format("%Y-%m-%d")
            .to_string()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio::Clip;
    use crate::bank::{Bank, Speaker};
    use crate::prompts::{library, Energy};
    use crate::quality::{analyze, config};
    use crate::synth;

    #[test]
    fn milestones_are_increasing() {
        assert!(MILESTONES.windows(2).all(|w| w[0].at < w[1].at));
        assert!(MILESTONES.iter().any(|m| m.at == RECOMMENDED_TAKES));
    }

    #[test]
    fn empty_bank() {
        let m = crate::bank::Manifest::new(Speaker::default());
        let p = progress(&m, library());
        assert_eq!(p.kept, 0);
        assert!(p.milestone.is_none());
        assert_eq!(p.next_milestone.unwrap().id, "first-words");
        assert_eq!(p.to_next, 0.0);
        assert!(p.phonemes_total > 30);
        assert_eq!(p.phonemes_covered, 0);
    }

    #[test]
    fn counts_takes_and_coverage() {
        let dir = tempfile::tempdir().unwrap();
        let mut bank = Bank::create(dir.path(), Speaker::default()).unwrap();
        let session = bank.start_session(Energy::Strong);
        let clip = synth::take(16_000, synth::Take::default());
        let good = analyze(&clip, None, config());
        let ids: Vec<String> = library()
            .sets()
            .next()
            .unwrap()
            .prompts
            .iter()
            .take(12)
            .map(|p| p.id.clone())
            .collect();
        for id in &ids {
            let prompt = bank.prompt_ref(id).unwrap();
            bank.keep_take(&prompt, &clip, good.clone(), Some(&session))
                .unwrap();
        }
        let silent = Clip::new(16_000, vec![0.0; 16_000]);
        let redo = analyze(&silent, None, config());
        let prompt = bank.prompt_ref("arctic_a0100").unwrap();
        bank.keep_take(&prompt, &silent, redo, Some(&session))
            .unwrap();

        let p = progress(&bank.manifest, library());
        assert_eq!(p.kept, 12);
        assert_eq!(p.needs_redo, 1);
        assert_eq!(p.milestone.unwrap().id, "first-words");
        assert_eq!(p.next_milestone.unwrap().id, "preview");
        assert!((p.to_next - 2.0 / 90.0).abs() < 1e-4, "{}", p.to_next);
        assert!(p.phonemes_covered > 20, "{}", p.phonemes_covered);
        assert!(p.diphones_covered > 50);
        assert!(p.speech_minutes > 0.2);
        assert_eq!(p.sessions, 1);
        assert_eq!(p.days_recorded, 1);
        assert_eq!(p.recent_days.len(), 1);
        assert_eq!(p.recent_days[0].kept, 12);
        assert_eq!(p.sets[0].recorded, 12);
    }
}
