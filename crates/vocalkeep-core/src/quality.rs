//! Recording quality checks.
//!
//! Every take is checked the moment it is recorded so problems can be fixed while the person is
//! still at the microphone, not discovered weeks later during training. The checks are tuned for
//! tired voices: anything that only *might* matter is a gentle note ("okay"), and only problems
//! that would hurt the trained voice ask for another try ("redo").
//!
//! The same algorithm, with the same thresholds (`shared/quality.json`), runs in the Python
//! training pipeline. `shared/fixtures/` holds recordings with expected results that both test
//! suites check, so the two never drift apart.

use std::sync::OnceLock;

use serde::{Deserialize, Serialize};

use crate::audio::{power_to_dbfs, Clip, MIN_DBFS};

/// Thresholds from `shared/quality.json`.
#[derive(Debug, Clone, Deserialize)]
pub struct QualityConfig {
    pub version: u32,
    pub frame_ms: u32,
    pub min_speech_run_frames: usize,
    pub speech_margin_db: f32,
    pub speech_floor_dbfs: f32,
    pub clip_level: f32,
    pub clip_run_samples: usize,
    pub clip_runs_redo: u32,
    pub near_clip_peak_dbfs: f32,
    pub quiet_warn_dbfs: f32,
    pub quiet_redo_dbfs: f32,
    pub loud_warn_dbfs: f32,
    pub noise_warn_dbfs: f32,
    pub noise_redo_dbfs: f32,
    pub snr_warn_db: f32,
    pub snr_redo_db: f32,
    pub dc_offset_warn: f32,
    pub min_speech_ms: u32,
    pub edge_margin_ms: u32,
    pub long_silence_warn_ms: u32,
    pub chars_per_second_max: f32,
    pub chars_per_second_min: f32,
    pub room: RoomConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RoomConfig {
    pub seconds: u32,
    pub quiet_dbfs: f32,
    pub fine_dbfs: f32,
    pub noisy_dbfs: f32,
}

/// The thresholds shipped with this build.
pub fn config() -> &'static QualityConfig {
    static CONFIG: OnceLock<QualityConfig> = OnceLock::new();
    CONFIG.get_or_init(|| {
        serde_json::from_str(include_str!("../../../shared/quality.json"))
            .expect("shared/quality.json is valid")
    })
}

/// Overall result for a take.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Verdict {
    /// Ready for training.
    Good,
    /// Usable, with a note that might help next time.
    Okay,
    /// Worth recording again.
    Redo,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Warn,
    Redo,
}

/// What was noticed. The app turns each code into a kind, plain-language message.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum IssueCode {
    NoSpeech,
    TooShort,
    Clipping,
    NearClipping,
    TooQuiet,
    TooLoud,
    Noisy,
    LowSnr,
    CutOffStart,
    CutOffEnd,
    LongPause,
    TooFast,
    TooSlow,
    DcOffset,
}

impl IssueCode {
    pub fn as_str(self) -> &'static str {
        match self {
            IssueCode::NoSpeech => "no-speech",
            IssueCode::TooShort => "too-short",
            IssueCode::Clipping => "clipping",
            IssueCode::NearClipping => "near-clipping",
            IssueCode::TooQuiet => "too-quiet",
            IssueCode::TooLoud => "too-loud",
            IssueCode::Noisy => "noisy",
            IssueCode::LowSnr => "low-snr",
            IssueCode::CutOffStart => "cut-off-start",
            IssueCode::CutOffEnd => "cut-off-end",
            IssueCode::LongPause => "long-pause",
            IssueCode::TooFast => "too-fast",
            IssueCode::TooSlow => "too-slow",
            IssueCode::DcOffset => "dc-offset",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Issue {
    pub code: IssueCode,
    pub severity: Severity,
}

/// Measurements and verdict for one take.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Analysis {
    pub verdict: Verdict,
    pub issues: Vec<Issue>,
    pub sample_rate: u32,
    pub duration_ms: u32,
    /// Highest sample, dBFS.
    pub peak_dbfs: f32,
    /// Average level while speaking, dBFS.
    pub speech_dbfs: f32,
    /// Background level between words, dBFS.
    pub noise_floor_dbfs: f32,
    /// Speech level above the background, dB.
    pub snr_db: f32,
    /// Samples at or above the clipping level.
    pub clipped_samples: u32,
    /// Runs of consecutive clipped samples (flattened peaks).
    pub clip_runs: u32,
    pub dc_offset: f32,
    pub speech_start_ms: Option<u32>,
    pub speech_end_ms: Option<u32>,
    pub speech_ms: u32,
    pub longest_pause_ms: u32,
}

impl Analysis {
    pub fn has(&self, code: IssueCode) -> bool {
        self.issues.iter().any(|i| i.code == code)
    }
}

/// Checks a take. `text` is the sentence that was read, if any; it enables the speaking-rate
/// check that catches a sentence cut short.
pub fn analyze(clip: &Clip, text: Option<&str>, cfg: &QualityConfig) -> Analysis {
    let sr = clip.sample_rate.max(1);
    let samples = &clip.samples;
    let duration_ms = clip.duration_ms();
    let frame_len = ((sr as u64 * cfg.frame_ms as u64) / 1000).max(1) as usize;

    // DC offset and clipping are measured on the raw signal.
    let dc = if samples.is_empty() {
        0.0
    } else {
        (samples.iter().map(|&s| s as f64).sum::<f64>() / samples.len() as f64) as f32
    };
    let (clipped_samples, clip_runs) = clipping(samples, cfg.clip_level, cfg.clip_run_samples);
    let peak = samples.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
    let peak_dbfs = crate::audio::amplitude_to_dbfs(peak);

    // Frame powers with the DC offset removed.
    let powers: Vec<f64> = samples
        .chunks(frame_len)
        .filter(|f| f.len() * 2 >= frame_len)
        .map(|f| {
            f.iter()
                .map(|&s| {
                    let v = (s - dc) as f64;
                    v * v
                })
                .sum::<f64>()
                / f.len() as f64
        })
        .collect();
    let frame_db: Vec<f32> = powers.iter().map(|&p| power_to_dbfs(p)).collect();

    let mut issues: Vec<Issue> = Vec::new();
    let push = |issues: &mut Vec<Issue>, code, severity| issues.push(Issue { code, severity });

    if frame_db.is_empty() {
        push(&mut issues, IssueCode::NoSpeech, Severity::Redo);
        return Analysis {
            verdict: Verdict::Redo,
            issues,
            sample_rate: sr,
            duration_ms,
            peak_dbfs,
            speech_dbfs: MIN_DBFS,
            noise_floor_dbfs: MIN_DBFS,
            snr_db: 0.0,
            clipped_samples,
            clip_runs,
            dc_offset: dc,
            speech_start_ms: None,
            speech_end_ms: None,
            speech_ms: 0,
            longest_pause_ms: 0,
        };
    }

    // Background: the mean power of the quietest tenth of frames.
    let noise_floor_dbfs = quietest_tenth_dbfs(&powers);
    let threshold = (noise_floor_dbfs + cfg.speech_margin_db).max(cfg.speech_floor_dbfs);
    let mut active: Vec<bool> = frame_db.iter().map(|&db| db > threshold).collect();
    drop_short_runs(&mut active, cfg.min_speech_run_frames);

    let first = active.iter().position(|&a| a);
    let last = active.iter().rposition(|&a| a);
    let speech_frames = active.iter().filter(|&&a| a).count();
    let speech_ms = (speech_frames as u32) * cfg.frame_ms;
    let speech_power = if speech_frames > 0 {
        powers
            .iter()
            .zip(&active)
            .filter(|(_, &a)| a)
            .map(|(&p, _)| p)
            .sum::<f64>()
            / speech_frames as f64
    } else {
        0.0
    };
    let speech_dbfs = power_to_dbfs(speech_power);
    let snr_db = if speech_frames > 0 {
        speech_dbfs - noise_floor_dbfs
    } else {
        0.0
    };
    let longest_pause_ms = match (first, last) {
        (Some(f), Some(l)) => longest_false_run(&active[f..=l]) as u32 * cfg.frame_ms,
        _ => 0,
    };
    let speech_start_ms = first.map(|f| f as u32 * cfg.frame_ms);
    let speech_end_ms = last.map(|l| (l as u32 + 1) * cfg.frame_ms);

    match (first, last) {
        (Some(f), Some(l)) => {
            if speech_ms < cfg.min_speech_ms {
                push(&mut issues, IssueCode::TooShort, Severity::Redo);
            }
            let edge_frames = (cfg.edge_margin_ms / cfg.frame_ms.max(1)) as usize;
            if f < edge_frames.max(1) {
                push(&mut issues, IssueCode::CutOffStart, Severity::Warn);
            }
            if active.len() - 1 - l < edge_frames.max(1) {
                push(&mut issues, IssueCode::CutOffEnd, Severity::Redo);
            }
        }
        _ => push(&mut issues, IssueCode::NoSpeech, Severity::Redo),
    }

    // Loudness and clipping.
    if clip_runs >= cfg.clip_runs_redo {
        push(&mut issues, IssueCode::Clipping, Severity::Redo);
    } else if clipped_samples > 0 || peak_dbfs > cfg.near_clip_peak_dbfs {
        push(&mut issues, IssueCode::NearClipping, Severity::Warn);
    }
    let mut level_issue = false;
    if speech_frames > 0 {
        if speech_dbfs < cfg.quiet_redo_dbfs {
            push(&mut issues, IssueCode::TooQuiet, Severity::Redo);
            level_issue = true;
        } else if speech_dbfs < cfg.quiet_warn_dbfs {
            push(&mut issues, IssueCode::TooQuiet, Severity::Warn);
            level_issue = true;
        } else if speech_dbfs > cfg.loud_warn_dbfs && clip_runs == 0 {
            push(&mut issues, IssueCode::TooLoud, Severity::Warn);
        }
    }

    // Background noise, then signal-to-noise when neither explains it already.
    if noise_floor_dbfs > cfg.noise_redo_dbfs {
        push(&mut issues, IssueCode::Noisy, Severity::Redo);
        level_issue = true;
    } else if noise_floor_dbfs > cfg.noise_warn_dbfs {
        push(&mut issues, IssueCode::Noisy, Severity::Warn);
        level_issue = true;
    }
    if speech_frames > 0 && !level_issue {
        if snr_db < cfg.snr_redo_db {
            push(&mut issues, IssueCode::LowSnr, Severity::Redo);
        } else if snr_db < cfg.snr_warn_db {
            push(&mut issues, IssueCode::LowSnr, Severity::Warn);
        }
    }

    if dc.abs() > cfg.dc_offset_warn {
        push(&mut issues, IssueCode::DcOffset, Severity::Warn);
    }
    if longest_pause_ms > cfg.long_silence_warn_ms {
        push(&mut issues, IssueCode::LongPause, Severity::Warn);
    }

    // Speaking rate against the sentence: catches a take that stopped early or ran on.
    if let (Some(text), Some(start), Some(end)) = (text, speech_start_ms, speech_end_ms) {
        let letters = text.chars().filter(|c| c.is_alphanumeric()).count();
        let span_s = (end.saturating_sub(start)) as f32 / 1000.0;
        if letters >= 10 && span_s > 0.0 {
            let cps = letters as f32 / span_s;
            if cps > cfg.chars_per_second_max {
                push(&mut issues, IssueCode::TooFast, Severity::Warn);
            } else if cps < cfg.chars_per_second_min {
                push(&mut issues, IssueCode::TooSlow, Severity::Warn);
            }
        }
    }

    let verdict = verdict_for(&issues);
    Analysis {
        verdict,
        issues,
        sample_rate: sr,
        duration_ms,
        peak_dbfs,
        speech_dbfs,
        noise_floor_dbfs,
        snr_db,
        clipped_samples,
        clip_runs,
        dc_offset: dc,
        speech_start_ms,
        speech_end_ms,
        speech_ms,
        longest_pause_ms,
    }
}

/// The verdict a list of issues adds up to.
pub fn verdict_for(issues: &[Issue]) -> Verdict {
    if issues.iter().any(|i| i.severity == Severity::Redo) {
        Verdict::Redo
    } else if issues.is_empty() {
        Verdict::Good
    } else {
        Verdict::Okay
    }
}

/// How quiet the room is, from a few seconds of silence.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum RoomLevel {
    Quiet,
    Fine,
    Noisy,
    TooNoisy,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RoomCheck {
    pub level: RoomLevel,
    /// Typical background level, dBFS.
    pub noise_floor_dbfs: f32,
    /// Loudest moment (a door, a cough), dBFS.
    pub peak_dbfs: f32,
    pub sample_rate: u32,
    pub checked_at: String,
}

/// Measures the room from a recording of silence.
pub fn analyze_room(clip: &Clip, cfg: &QualityConfig) -> RoomCheck {
    let frame_len = ((clip.sample_rate.max(1) as u64 * cfg.frame_ms as u64) / 1000).max(1) as usize;
    let mut powers: Vec<f64> = clip
        .samples
        .chunks(frame_len)
        .filter(|f| f.len() * 2 >= frame_len)
        .map(|f| f.iter().map(|&s| (s as f64) * (s as f64)).sum::<f64>() / f.len() as f64)
        .collect();
    powers.sort_by(|a, b| a.total_cmp(b));
    // The median frame ignores a single cough or door; the peak reports it.
    let noise = powers
        .get(powers.len() / 2)
        .map(|&p| power_to_dbfs(p))
        .unwrap_or(MIN_DBFS);
    let level = if noise <= cfg.room.quiet_dbfs {
        RoomLevel::Quiet
    } else if noise <= cfg.room.fine_dbfs {
        RoomLevel::Fine
    } else if noise <= cfg.room.noisy_dbfs {
        RoomLevel::Noisy
    } else {
        RoomLevel::TooNoisy
    };
    RoomCheck {
        level,
        noise_floor_dbfs: noise,
        peak_dbfs: crate::audio::peak_dbfs(&clip.samples),
        sample_rate: clip.sample_rate,
        checked_at: crate::now_rfc3339(),
    }
}

fn clipping(samples: &[f32], level: f32, min_run: usize) -> (u32, u32) {
    let mut clipped = 0u32;
    let mut runs = 0u32;
    let mut run = 0usize;
    for &s in samples {
        if s.abs() >= level {
            clipped += 1;
            run += 1;
        } else {
            if run >= min_run.max(1) {
                runs += 1;
            }
            run = 0;
        }
    }
    if run >= min_run.max(1) {
        runs += 1;
    }
    (clipped, runs)
}

fn quietest_tenth_dbfs(powers: &[f64]) -> f32 {
    let mut sorted = powers.to_vec();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let n = (sorted.len() / 10).max(1);
    power_to_dbfs(sorted[..n].iter().sum::<f64>() / n as f64)
}

/// Clears runs of `true` shorter than `min_run` (clicks and taps are not speech).
fn drop_short_runs(active: &mut [bool], min_run: usize) {
    let mut i = 0;
    while i < active.len() {
        if active[i] {
            let start = i;
            while i < active.len() && active[i] {
                i += 1;
            }
            if i - start < min_run {
                active[start..i].iter_mut().for_each(|a| *a = false);
            }
        } else {
            i += 1;
        }
    }
}

fn longest_false_run(active: &[bool]) -> usize {
    let mut best = 0;
    let mut run = 0;
    for &a in active {
        if a {
            run = 0;
        } else {
            run += 1;
            best = best.max(run);
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::synth;

    fn codes(a: &Analysis) -> Vec<&'static str> {
        a.issues.iter().map(|i| i.code.as_str()).collect()
    }

    #[test]
    fn config_loads() {
        let cfg = config();
        assert_eq!(cfg.version, 1);
        assert!(cfg.quiet_redo_dbfs < cfg.quiet_warn_dbfs);
        assert!(cfg.noise_warn_dbfs < cfg.noise_redo_dbfs);
        assert!(cfg.snr_redo_db < cfg.snr_warn_db);
    }

    #[test]
    fn clean_take_is_good() {
        let clip = synth::take(16_000, synth::Take::default());
        let a = analyze(&clip, Some("The quick brown fox jumps."), config());
        assert_eq!(a.verdict, Verdict::Good, "{:?}", codes(&a));
        assert!(a.snr_db > 40.0, "{a:?}");
        assert!(a.speech_start_ms.unwrap() >= 300);
    }

    #[test]
    fn silence_has_no_speech() {
        let clip = Clip::new(16_000, synth::noise(16_000, 1.5, -70.0, 7));
        let a = analyze(&clip, None, config());
        assert_eq!(a.verdict, Verdict::Redo);
        assert!(a.has(IssueCode::NoSpeech));
    }

    #[test]
    fn empty_clip_has_no_speech() {
        let a = analyze(&Clip::new(16_000, vec![]), None, config());
        assert_eq!(a.verdict, Verdict::Redo);
        assert!(a.has(IssueCode::NoSpeech));
    }

    #[test]
    fn clipped_take_is_redone() {
        let clip = synth::take(
            16_000,
            synth::Take {
                level_dbfs: 3.0,
                ..Default::default()
            },
        );
        let a = analyze(&clip, None, config());
        assert_eq!(a.verdict, Verdict::Redo);
        assert!(a.has(IssueCode::Clipping), "{:?}", codes(&a));
        assert!(a.clip_runs >= 1);
    }

    #[test]
    fn quiet_take_is_noted_then_redone() {
        let make = |db| {
            synth::take(
                16_000,
                synth::Take {
                    level_dbfs: db,
                    noise_dbfs: -85.0,
                    ..Default::default()
                },
            )
        };
        let a = analyze(&make(-33.0), None, config());
        assert_eq!(a.verdict, Verdict::Okay, "{:?}", codes(&a));
        assert!(a.has(IssueCode::TooQuiet));
        let a = analyze(&make(-46.0), None, config());
        assert_eq!(a.verdict, Verdict::Redo, "{:?}", codes(&a));
        assert!(a.has(IssueCode::TooQuiet));
    }

    #[test]
    fn noisy_room_is_flagged() {
        let clip = synth::take(
            16_000,
            synth::Take {
                noise_dbfs: -34.0,
                ..Default::default()
            },
        );
        let a = analyze(&clip, None, config());
        assert_eq!(a.verdict, Verdict::Redo, "{a:?}");
        assert!(a.has(IssueCode::Noisy));
        assert!(!a.has(IssueCode::LowSnr), "not reported twice");
    }

    #[test]
    fn cut_off_end_is_redone() {
        let clip = synth::take(
            16_000,
            synth::Take {
                tail_s: 0.0,
                ..Default::default()
            },
        );
        let a = analyze(&clip, None, config());
        assert!(a.has(IssueCode::CutOffEnd), "{:?}", codes(&a));
        assert_eq!(a.verdict, Verdict::Redo);
    }

    #[test]
    fn early_start_is_a_note() {
        let clip = synth::take(
            16_000,
            synth::Take {
                lead_s: 0.0,
                ..Default::default()
            },
        );
        let a = analyze(&clip, None, config());
        assert!(a.has(IssueCode::CutOffStart), "{:?}", codes(&a));
        assert_eq!(a.verdict, Verdict::Okay);
    }

    #[test]
    fn long_text_for_short_speech_is_too_fast() {
        let clip = synth::take(
            16_000,
            synth::Take {
                speech_s: 0.6,
                ..Default::default()
            },
        );
        let text = "This sentence has far too many letters to fit in a little over half a second.";
        let a = analyze(&clip, Some(text), config());
        assert!(a.has(IssueCode::TooFast), "{:?}", codes(&a));
    }

    #[test]
    fn long_pause_is_noted() {
        let clip = synth::take(
            16_000,
            synth::Take {
                gap_s: 3.0,
                ..Default::default()
            },
        );
        let a = analyze(&clip, None, config());
        assert!(a.has(IssueCode::LongPause), "{:?}", codes(&a));
        assert!(a.longest_pause_ms >= 2900);
    }

    #[test]
    fn dc_offset_is_noted() {
        let mut clip = synth::take(16_000, synth::Take::default());
        clip.samples.iter_mut().for_each(|s| *s += 0.05);
        let a = analyze(&clip, None, config());
        assert!(a.has(IssueCode::DcOffset), "{:?}", codes(&a));
        // Offset is removed before measuring, so speech is still found.
        assert!(a.speech_ms > 500);
    }

    #[test]
    fn single_click_is_not_speech() {
        let mut samples = synth::noise(16_000, 1.5, -75.0, 3);
        samples[8000] = 0.6;
        let a = analyze(&Clip::new(16_000, samples), None, config());
        assert!(a.has(IssueCode::NoSpeech), "{:?}", codes(&a));
    }

    #[test]
    fn room_levels() {
        let cfg = config();
        let quiet = analyze_room(&Clip::new(16_000, synth::noise(16_000, 2.0, -70.0, 1)), cfg);
        assert_eq!(quiet.level, RoomLevel::Quiet);
        let fine = analyze_room(&Clip::new(16_000, synth::noise(16_000, 2.0, -55.0, 1)), cfg);
        assert_eq!(fine.level, RoomLevel::Fine);
        let noisy = analyze_room(&Clip::new(16_000, synth::noise(16_000, 2.0, -45.0, 1)), cfg);
        assert_eq!(noisy.level, RoomLevel::Noisy);
        let loud = analyze_room(&Clip::new(16_000, synth::noise(16_000, 2.0, -30.0, 1)), cfg);
        assert_eq!(loud.level, RoomLevel::TooNoisy);
    }

    #[test]
    fn issue_codes_serialize_kebab_case() {
        let json = serde_json::to_string(&IssueCode::CutOffEnd).unwrap();
        assert_eq!(json, "\"cut-off-end\"");
        for code in [IssueCode::NoSpeech, IssueCode::LowSnr, IssueCode::DcOffset] {
            assert_eq!(
                serde_json::to_string(&code).unwrap(),
                format!("\"{}\"", code.as_str())
            );
        }
    }
}
