//! Microphone capture with a live level meter.
//!
//! The cpal stream lives on its own thread (streams aren't `Send` on every platform). Audio is
//! mixed to mono and kept in memory at the device's own sample rate; the quality checks and the
//! WAV writer take it from there. A short tail keeps recording after Stop is pressed, so the end
//! of the last word is never cut off.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Data, SampleFormat};
use parking_lot::Mutex;
use serde::Serialize;
use vocalkeep_core::audio::{amplitude_to_dbfs, mix_to_mono, power_to_dbfs, Clip};

/// Kept after Stop is pressed so trailing sounds aren't clipped.
pub const STOP_TAIL: Duration = Duration::from_millis(300);
const METER_INTERVAL: Duration = Duration::from_millis(50);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InputDevice {
    pub id: String,
    pub name: String,
    pub is_default: bool,
}

/// One reading of the level meter.
#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Level {
    pub rms_dbfs: f32,
    pub peak_dbfs: f32,
    pub clipping: bool,
    pub elapsed_ms: u64,
    /// The recording reached its length limit and stopped growing.
    pub limit_reached: bool,
}

pub fn list_devices() -> Result<Vec<InputDevice>> {
    let host = cpal::default_host();
    let default_id = host.default_input_device().and_then(|d| device_id(&d));
    let mut out = Vec::new();
    for device in host.input_devices().context("could not list microphones")? {
        let Some(id) = device_id(&device) else {
            continue;
        };
        if out.iter().any(|d: &InputDevice| d.id == id) {
            continue;
        }
        out.push(InputDevice {
            is_default: Some(&id) == default_id.as_ref(),
            name: device_name(&device),
            id,
        });
    }
    out.sort_by_key(|d| !d.is_default);
    Ok(out)
}

fn device_id(device: &cpal::Device) -> Option<String> {
    device.id().ok().map(|id| id.to_string())
}

fn device_name(device: &cpal::Device) -> String {
    device
        .description()
        .map(|d| d.name().to_string())
        .unwrap_or_else(|_| "Microphone".to_string())
}

fn find_device(wanted: Option<&str>) -> Result<cpal::Device> {
    let host = cpal::default_host();
    if let Some(wanted) = wanted {
        if let Ok(mut devices) = host.input_devices() {
            if let Some(d) = devices.find(|d| device_id(d).as_deref() == Some(wanted)) {
                return Ok(d);
            }
        }
        log::warn!("microphone {wanted} not found; using the default");
    }
    host.default_input_device()
        .ok_or_else(|| anyhow!("No microphone was found. Plug one in and try again."))
}

#[derive(Default)]
struct MeterState {
    peak: f32,
    sum_sq: f64,
    count: usize,
    clipped: bool,
}

struct Shared {
    samples: Mutex<Vec<f32>>,
    meter: Mutex<MeterState>,
    error: Mutex<Option<String>>,
    max_samples: usize,
    limit_reached: AtomicBool,
}

struct Active {
    shared: Arc<Shared>,
    stop: Arc<AtomicBool>,
    capture: JoinHandle<()>,
    meter: JoinHandle<()>,
    sample_rate: u32,
}

/// One recording at a time.
#[derive(Default)]
pub struct Recorder {
    active: Mutex<Option<Active>>,
}

impl Recorder {
    pub fn is_recording(&self) -> bool {
        self.active.lock().is_some()
    }

    /// Starts recording. `on_level` is called about 20 times a second.
    pub fn start(
        &self,
        device: Option<&str>,
        max_seconds: u32,
        on_level: impl Fn(Level) + Send + 'static,
    ) -> Result<u32> {
        let mut guard = self.active.lock();
        if guard.is_some() {
            bail!("Already recording.");
        }
        let stop = Arc::new(AtomicBool::new(false));
        let (ready_tx, ready_rx) = mpsc::channel::<Result<(u32, Arc<Shared>), String>>();
        let device = device.map(str::to_string);
        let stop_capture = stop.clone();
        let capture = std::thread::Builder::new()
            .name("vocalkeep-capture".into())
            .spawn(move || capture_thread(device, max_seconds, stop_capture, ready_tx))
            .context("could not start the recording thread")?;
        let (sample_rate, shared) = match ready_rx.recv_timeout(Duration::from_secs(10)) {
            Ok(Ok(v)) => v,
            Ok(Err(e)) => {
                let _ = capture.join();
                bail!("{e}");
            }
            Err(_) => {
                stop.store(true, Ordering::SeqCst);
                bail!("The microphone didn't respond. Check it is connected and not in use.");
            }
        };

        let started = Instant::now();
        let meter_shared = shared.clone();
        let meter_stop = stop.clone();
        let meter = std::thread::Builder::new()
            .name("vocalkeep-meter".into())
            .spawn(move || {
                while !meter_stop.load(Ordering::SeqCst) {
                    std::thread::sleep(METER_INTERVAL);
                    let m = std::mem::take(&mut *meter_shared.meter.lock());
                    let rms = if m.count > 0 {
                        power_to_dbfs(m.sum_sq / m.count as f64)
                    } else {
                        vocalkeep_core::audio::MIN_DBFS
                    };
                    on_level(Level {
                        rms_dbfs: rms,
                        peak_dbfs: amplitude_to_dbfs(m.peak),
                        clipping: m.clipped,
                        elapsed_ms: started.elapsed().as_millis() as u64,
                        limit_reached: meter_shared.limit_reached.load(Ordering::SeqCst),
                    });
                }
            })
            .context("could not start the level meter")?;

        *guard = Some(Active {
            shared,
            stop,
            capture,
            meter,
            sample_rate,
        });
        Ok(sample_rate)
    }

    /// Stops after `tail` and returns the recording.
    pub fn stop(&self, tail: Duration) -> Result<Clip> {
        let active = self
            .active
            .lock()
            .take()
            .ok_or_else(|| anyhow!("Nothing is being recorded."))?;
        std::thread::sleep(tail);
        active.stop.store(true, Ordering::SeqCst);
        let _ = active.capture.join();
        let _ = active.meter.join();
        if let Some(e) = active.shared.error.lock().take() {
            if active.shared.samples.lock().is_empty() {
                bail!("The microphone stopped working: {e}");
            }
            log::warn!("audio stream error during recording: {e}");
        }
        let samples = std::mem::take(&mut *active.shared.samples.lock());
        Ok(Clip::new(active.sample_rate, samples))
    }

    /// Stops and throws the recording away.
    pub fn cancel(&self) {
        if let Some(active) = self.active.lock().take() {
            active.stop.store(true, Ordering::SeqCst);
            let _ = active.capture.join();
            let _ = active.meter.join();
        }
    }
}

type Ready = mpsc::Sender<Result<(u32, Arc<Shared>), String>>;

fn capture_thread(device: Option<String>, max_seconds: u32, stop: Arc<AtomicBool>, ready: Ready) {
    let opened = (|| -> Result<(cpal::Stream, u32, Arc<Shared>)> {
        let device = find_device(device.as_deref())?;
        let config = device
            .default_input_config()
            .context("Could not read the microphone's settings.")?;
        let format = config.sample_format();
        let stream_config = config.config();
        let channels = stream_config.channels as usize;
        let rate = stream_config.sample_rate;
        let shared = Arc::new(Shared {
            samples: Mutex::new(Vec::with_capacity(rate as usize * 30)),
            meter: Mutex::new(MeterState::default()),
            error: Mutex::new(None),
            max_samples: rate as usize * max_seconds.max(1) as usize,
            limit_reached: AtomicBool::new(false),
        });
        let err_shared = shared.clone();
        let on_error = move |e: cpal::Error| {
            *err_shared.error.lock() = Some(e.to_string());
        };
        macro_rules! build {
            ($t:ty) => {{
                let shared = shared.clone();
                device.build_input_stream_raw(
                    stream_config,
                    format,
                    move |data: &Data, _: &cpal::InputCallbackInfo| {
                        on_audio::<$t>(data, channels, &shared)
                    },
                    on_error,
                    Some(Duration::from_secs(5)),
                )
            }};
        }
        let stream = match format {
            SampleFormat::F32 => build!(f32),
            SampleFormat::F64 => build!(f64),
            SampleFormat::I16 => build!(i16),
            SampleFormat::I32 => build!(i32),
            SampleFormat::I24 => build!(cpal::I24),
            SampleFormat::I8 => build!(i8),
            SampleFormat::U8 => build!(u8),
            SampleFormat::U16 => build!(u16),
            SampleFormat::U32 => build!(u32),
            other => bail!("This microphone uses an audio format Vocalkeep can't read ({other})."),
        }
        .map_err(|e| anyhow!("Could not open the microphone: {e}"))?;
        stream
            .play()
            .map_err(|e| anyhow!("Could not start the microphone: {e}"))?;
        Ok((stream, rate, shared))
    })();

    match opened {
        Ok((stream, rate, shared)) => {
            let _ = ready.send(Ok((rate, shared)));
            while !stop.load(Ordering::SeqCst) {
                std::thread::sleep(Duration::from_millis(10));
            }
            drop(stream);
        }
        Err(e) => {
            let _ = ready.send(Err(format!("{e:#}")));
        }
    }
}

fn on_audio<T>(data: &Data, channels: usize, shared: &Shared)
where
    T: cpal::SizedSample,
    f32: cpal::FromSample<T>,
{
    let Some(raw) = data.as_slice::<T>() else {
        return;
    };
    let floats: Vec<f32> = raw
        .iter()
        .map(|&s| cpal::Sample::to_sample::<f32>(s))
        .collect();
    let mono = mix_to_mono(&floats, channels);
    {
        let mut m = shared.meter.lock();
        for &s in &mono {
            let a = s.abs();
            m.peak = m.peak.max(a);
            m.sum_sq += (s as f64) * (s as f64);
            if a >= 0.995 {
                m.clipped = true;
            }
        }
        m.count += mono.len();
    }
    let mut samples = shared.samples.lock();
    let room = shared.max_samples.saturating_sub(samples.len());
    if room < mono.len() {
        shared.limit_reached.store(true, Ordering::SeqCst);
    }
    samples.extend_from_slice(&mono[..room.min(mono.len())]);
}

#[cfg(test)]
mod tests {
    use super::*;
    use vocalkeep_core::quality::{analyze, config, Verdict};

    /// Records from the default microphone while a fixture plays into the default speaker.
    /// CI runs this against a PulseAudio null sink whose monitor is the default source:
    /// `cargo test -p vocalkeep-desktop -- --ignored microphone`.
    #[test]
    #[ignore = "needs an audio server; see .github/workflows/ci.yml"]
    fn microphone_records_what_is_played() {
        let fixture =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../shared/fixtures/good.wav");
        let levels = Arc::new(Mutex::new(Vec::<Level>::new()));
        let sink = levels.clone();
        let recorder = Recorder::default();
        let rate = recorder
            .start(None, 20, move |l| sink.lock().push(l))
            .expect("the default microphone opens");
        assert!(rate >= 8_000, "sample rate {rate}");
        assert!(recorder.is_recording());
        assert!(
            recorder.start(None, 20, |_| {}).is_err(),
            "one recording at a time"
        );

        std::thread::sleep(Duration::from_millis(300));
        let played = std::process::Command::new("paplay")
            .arg(&fixture)
            .status()
            .expect("paplay runs");
        assert!(played.success());
        let clip = recorder.stop(STOP_TAIL).expect("the recording stops");
        assert!(!recorder.is_recording());

        assert!(clip.duration_ms() > 2_000, "{} ms", clip.duration_ms());
        let levels = levels.lock();
        assert!(levels.len() > 20, "{} level readings", levels.len());
        assert!(
            levels.iter().any(|l| l.rms_dbfs > -40.0),
            "the meter saw speech"
        );
        let a = analyze(&clip, Some("The quick brown fox jumps."), config());
        assert_ne!(a.verdict, Verdict::Redo, "{a:?}");
        assert!(a.speech_ms > 1_000, "{a:?}");
    }

    #[test]
    fn stopping_without_recording_is_an_error() {
        let recorder = Recorder::default();
        assert!(recorder.stop(Duration::ZERO).is_err());
        recorder.cancel();
        assert!(!recorder.is_recording());
    }
}
