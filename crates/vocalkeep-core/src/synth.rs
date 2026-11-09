//! Deterministic test signals: background noise and a speech-like voiced sound.
//!
//! Used by the test suite and the room-check self-test. Nothing here is ever saved as a
//! recording.

use crate::audio::{dbfs_to_amplitude, Clip};

/// White noise at an RMS level, from a fixed seed so tests are repeatable.
pub fn noise(sample_rate: u32, seconds: f32, rms_dbfs: f32, seed: u64) -> Vec<f32> {
    let n = (sample_rate as f32 * seconds).round() as usize;
    let amp = dbfs_to_amplitude(rms_dbfs) * 3f32.sqrt();
    let mut rng = XorShift(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1);
    (0..n).map(|_| (rng.next_f32() * 2.0 - 1.0) * amp).collect()
}

/// Shape of a synthetic take.
#[derive(Debug, Clone, Copy)]
pub struct Take {
    /// Silence before speaking, seconds.
    pub lead_s: f32,
    /// Speaking time, seconds (split in two halves around `gap_s`).
    pub speech_s: f32,
    /// A pause in the middle of the sentence, seconds.
    pub gap_s: f32,
    /// Silence after speaking, seconds.
    pub tail_s: f32,
    /// RMS level of the voice, dBFS. Above 0 it clips.
    pub level_dbfs: f32,
    /// RMS level of the room, dBFS.
    pub noise_dbfs: f32,
    pub seed: u64,
}

impl Default for Take {
    fn default() -> Self {
        Self {
            lead_s: 0.4,
            speech_s: 1.6,
            gap_s: 0.0,
            tail_s: 0.4,
            level_dbfs: -20.0,
            noise_dbfs: -70.0,
            seed: 42,
        }
    }
}

/// A speech-like take: a voiced sound with harmonics, a gentle pitch drift and syllable rhythm.
pub fn take(sample_rate: u32, t: Take) -> Clip {
    let total = t.lead_s + t.speech_s + t.gap_s + t.tail_s;
    let mut samples = noise(sample_rate, total, t.noise_dbfs, t.seed);
    let sr = sample_rate as f32;
    let half = t.speech_s / 2.0;
    let segments = [
        (t.lead_s, half),
        (t.lead_s + half + t.gap_s, t.speech_s - half),
    ];
    // Voiced signal normalised so its RMS over the speaking time is `level_dbfs`.
    let target = dbfs_to_amplitude(t.level_dbfs);
    let mut voiced: Vec<(usize, f32)> = Vec::new();
    for (start, len) in segments {
        let first = (start * sr) as usize;
        let count = (len * sr) as usize;
        for i in 0..count {
            let time = i as f32 / sr;
            let f0 = 140.0 + 12.0 * (2.0 * std::f32::consts::PI * 0.7 * time).sin();
            let phase = 2.0 * std::f32::consts::PI * f0 * time;
            let tone: f32 = (1..=6).map(|h| (phase * h as f32).sin() / h as f32).sum();
            let syllable = (std::f32::consts::PI * 4.0 * time).sin().abs().powf(0.6);
            voiced.push((first + i, tone * syllable));
        }
    }
    let rms = (voiced.iter().map(|(_, v)| v * v).sum::<f32>() / voiced.len().max(1) as f32).sqrt();
    let gain = if rms > 0.0 { target / rms } else { 0.0 };
    for (i, v) in voiced {
        if let Some(s) = samples.get_mut(i) {
            *s = (*s + v * gain).clamp(-1.0, 1.0);
        }
    }
    Clip::new(sample_rate, samples)
}

struct XorShift(u64);

impl XorShift {
    fn next_f32(&mut self) -> f32 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        (x >> 40) as f32 / (1u64 << 24) as f32
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio::rms_dbfs;

    #[test]
    fn noise_has_requested_level() {
        let n = noise(16_000, 2.0, -40.0, 9);
        assert!((rms_dbfs(&n) + 40.0).abs() < 0.5, "{}", rms_dbfs(&n));
    }

    #[test]
    fn noise_is_deterministic() {
        assert_eq!(noise(8_000, 0.1, -30.0, 5), noise(8_000, 0.1, -30.0, 5));
        assert_ne!(noise(8_000, 0.1, -30.0, 5), noise(8_000, 0.1, -30.0, 6));
    }

    #[test]
    fn take_has_expected_length() {
        let clip = take(16_000, Take::default());
        assert_eq!(clip.duration_ms(), 2400);
    }
}
