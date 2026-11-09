//! Audio helpers: decibels, mixing to mono and reading/writing WAV files.
//!
//! Vocalkeep stores every recording as 16-bit PCM mono WAV at the microphone's own sample rate.
//! That is lossless, opens in every audio tool, and is what the training pipeline expects.

use std::fs::File;
use std::io::BufWriter;
use std::path::Path;

use anyhow::{bail, Context, Result};

/// The quietest level we report. Digital silence would otherwise be minus infinity.
pub const MIN_DBFS: f32 = -96.0;

/// Converts a linear amplitude (0..1) to dBFS.
pub fn amplitude_to_dbfs(amplitude: f32) -> f32 {
    if amplitude <= 0.0 || !amplitude.is_finite() {
        return MIN_DBFS;
    }
    (20.0 * amplitude.log10()).max(MIN_DBFS)
}

/// Converts mean power (mean of squared samples) to dBFS.
pub fn power_to_dbfs(power: f64) -> f32 {
    if power <= 0.0 || !power.is_finite() {
        return MIN_DBFS;
    }
    ((10.0 * power.log10()) as f32).max(MIN_DBFS)
}

/// Converts dBFS to a linear amplitude.
pub fn dbfs_to_amplitude(dbfs: f32) -> f32 {
    10f32.powf(dbfs / 20.0)
}

/// Root-mean-square level of a block in dBFS.
pub fn rms_dbfs(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return MIN_DBFS;
    }
    let power = samples
        .iter()
        .map(|&s| (s as f64) * (s as f64))
        .sum::<f64>()
        / samples.len() as f64;
    power_to_dbfs(power)
}

/// Peak absolute sample value of a block in dBFS.
pub fn peak_dbfs(samples: &[f32]) -> f32 {
    amplitude_to_dbfs(samples.iter().fold(0.0f32, |m, &s| m.max(s.abs())))
}

/// Averages interleaved channels into one.
pub fn mix_to_mono(interleaved: &[f32], channels: usize) -> Vec<f32> {
    if channels <= 1 {
        return interleaved.to_vec();
    }
    interleaved
        .chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / frame.len() as f32)
        .collect()
}

/// A mono recording in memory.
#[derive(Debug, Clone, PartialEq)]
pub struct Clip {
    pub sample_rate: u32,
    pub samples: Vec<f32>,
}

impl Clip {
    pub fn new(sample_rate: u32, samples: Vec<f32>) -> Self {
        Self {
            sample_rate,
            samples,
        }
    }

    pub fn duration_ms(&self) -> u32 {
        if self.sample_rate == 0 {
            return 0;
        }
        ((self.samples.len() as u64 * 1000) / self.sample_rate as u64) as u32
    }

    /// Samples for `ms` milliseconds at this clip's rate.
    pub fn samples_for_ms(&self, ms: u32) -> usize {
        (self.sample_rate as u64 * ms as u64 / 1000) as usize
    }
}

/// Writes a mono clip as 16-bit PCM WAV. Samples outside -1..1 are clamped.
pub fn write_wav(path: &Path, clip: &Clip) -> Result<()> {
    if clip.sample_rate == 0 {
        bail!("cannot write a WAV file with a sample rate of 0");
    }
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: clip.sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("creating folder {}", parent.display()))?;
    }
    let file = File::create(path).with_context(|| format!("creating {}", path.display()))?;
    let mut writer = hound::WavWriter::new(BufWriter::new(file), spec)?;
    for &s in &clip.samples {
        writer.write_sample(f32_to_i16(s))?;
    }
    writer.finalize()?;
    Ok(())
}

/// Encodes a mono clip as a 16-bit PCM WAV in memory (for playback in the app).
pub fn wav_bytes(clip: &Clip) -> Result<Vec<u8>> {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: clip.sample_rate.max(1),
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut cursor = std::io::Cursor::new(Vec::with_capacity(44 + clip.samples.len() * 2));
    {
        let mut writer = hound::WavWriter::new(&mut cursor, spec)?;
        for &s in &clip.samples {
            writer.write_sample(f32_to_i16(s))?;
        }
        writer.finalize()?;
    }
    Ok(cursor.into_inner())
}

/// Reads any PCM or float WAV file and mixes it to mono.
pub fn read_wav(path: &Path) -> Result<Clip> {
    let mut reader =
        hound::WavReader::open(path).with_context(|| format!("opening {}", path.display()))?;
    let spec = reader.spec();
    let channels = spec.channels.max(1) as usize;
    let interleaved: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => reader.samples::<f32>().collect::<Result<_, _>>()?,
        hound::SampleFormat::Int => {
            let bits = spec.bits_per_sample;
            if bits == 0 || bits > 32 {
                bail!("{}: unsupported bit depth {bits}", path.display());
            }
            let scale = (1i64 << (bits - 1)) as f32;
            reader
                .samples::<i32>()
                .map(|s| s.map(|v| v as f32 / scale))
                .collect::<Result<_, _>>()?
        }
    };
    Ok(Clip::new(
        spec.sample_rate,
        mix_to_mono(&interleaved, channels),
    ))
}

fn f32_to_i16(s: f32) -> i16 {
    let s = if s.is_finite() {
        s.clamp(-1.0, 1.0)
    } else {
        0.0
    };
    // Symmetric scaling: full scale maps to ±32767 so a clean round trip never clips.
    (s * i16::MAX as f32).round() as i16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decibel_conversions() {
        assert!((amplitude_to_dbfs(1.0) - 0.0).abs() < 1e-6);
        assert!((amplitude_to_dbfs(0.5) + 6.0206).abs() < 1e-3);
        assert_eq!(amplitude_to_dbfs(0.0), MIN_DBFS);
        assert!((dbfs_to_amplitude(-20.0) - 0.1).abs() < 1e-6);
        assert_eq!(power_to_dbfs(0.0), MIN_DBFS);
    }

    #[test]
    fn sine_rms_is_minus_three_db_of_peak() {
        let sr = 16_000;
        let samples: Vec<f32> = (0..sr)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * 440.0 * i as f32 / sr as f32).sin())
            .collect();
        let rms = rms_dbfs(&samples);
        let peak = peak_dbfs(&samples);
        assert!((peak - rms - 3.01).abs() < 0.05, "peak {peak} rms {rms}");
    }

    #[test]
    fn mono_mix_averages_channels() {
        assert_eq!(mix_to_mono(&[1.0, 0.0, 0.5, 0.5], 2), vec![0.5, 0.5]);
        assert_eq!(mix_to_mono(&[0.25, 0.75], 1), vec![0.25, 0.75]);
    }

    #[test]
    fn wav_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested").join("take.wav");
        let clip = Clip::new(22_050, vec![0.0, 0.5, -0.5, 1.0, -1.0, 2.0]);
        write_wav(&path, &clip).unwrap();
        let back = read_wav(&path).unwrap();
        assert_eq!(back.sample_rate, 22_050);
        assert_eq!(back.samples.len(), 6);
        assert!((back.samples[1] - 0.5).abs() < 1e-3);
        assert!(back.samples[5] <= 1.0, "clamped");
        let bytes = wav_bytes(&clip).unwrap();
        assert_eq!(&bytes[0..4], b"RIFF");
        assert_eq!(bytes.len(), 44 + 6 * 2);
    }

    #[test]
    fn durations() {
        let clip = Clip::new(48_000, vec![0.0; 24_000]);
        assert_eq!(clip.duration_ms(), 500);
        assert_eq!(clip.samples_for_ms(20), 960);
    }
}
