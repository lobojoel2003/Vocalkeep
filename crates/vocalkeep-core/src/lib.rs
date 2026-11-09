//! Vocalkeep core: everything the recording app needs that isn't the user interface or the
//! microphone.
//!
//! - [`quality`]: checks each take for clipping, level, background noise and cut-off words.
//! - [`bank`]: the voice bank on disk (`bank.json` plus WAV files).
//! - [`prompts`]: the built-in sentence sets and the order they're offered in.
//! - [`progress`]: milestones and how many of the language's sounds are covered.
//! - [`export`]: backups, restores and legacy-message folders.

pub mod audio;
pub mod bank;
pub mod build_info;
pub mod export;
pub mod progress;
pub mod prompts;
pub mod quality;
pub mod synth;

/// The current time as an RFC 3339 UTC timestamp with second precision.
pub fn now_rfc3339() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}
