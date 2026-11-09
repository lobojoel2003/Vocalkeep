//! The quality checker must agree with `shared/fixtures/expected.json`, which the Python
//! pipeline checks too.

use std::path::PathBuf;

use serde::Deserialize;
use vocalkeep_core::audio::read_wav;
use vocalkeep_core::quality::{analyze, config};

#[derive(Deserialize)]
struct Expected {
    file: String,
    text: Option<String>,
    verdict: String,
    issues: Vec<String>,
}

#[test]
fn fixtures_match_expected_verdicts() {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../shared/fixtures");
    let expected: Vec<Expected> =
        serde_json::from_str(&std::fs::read_to_string(dir.join("expected.json")).unwrap()).unwrap();
    assert!(expected.len() >= 10);
    let mut failures = Vec::new();
    for case in expected {
        let clip = read_wav(&dir.join(&case.file)).unwrap();
        let a = analyze(&clip, case.text.as_deref(), config());
        let verdict = serde_json::to_value(a.verdict).unwrap();
        let mut got: Vec<String> = a
            .issues
            .iter()
            .map(|i| i.code.as_str().to_string())
            .collect();
        let mut want = case.issues.clone();
        got.sort();
        want.sort();
        if verdict != case.verdict || got != want {
            failures.push(format!(
                "{}: expected {} {:?}, got {} {:?} (speech {:.1} dBFS, noise {:.1} dBFS, snr {:.1} dB)",
                case.file,
                case.verdict,
                want,
                verdict,
                got,
                a.speech_dbfs,
                a.noise_floor_dbfs,
                a.snr_db
            ));
        }
    }
    assert!(failures.is_empty(), "\n{}", failures.join("\n"));
}
