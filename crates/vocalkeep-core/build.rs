//! Embeds the build number, commit and date so the app can show exactly which build it is.
//! CI sets VOCALKEEP_BUILD_NUMBER (the Actions run number) and VOCALKEEP_GIT_SHA.

use std::process::Command;

fn main() {
    println!("cargo:rerun-if-env-changed=VOCALKEEP_BUILD_NUMBER");
    println!("cargo:rerun-if-env-changed=VOCALKEEP_GIT_SHA");
    println!("cargo:rerun-if-env-changed=SOURCE_DATE_EPOCH");
    println!("cargo:rerun-if-changed=../../shared/quality.json");
    println!("cargo:rerun-if-changed=../../shared/prompts");

    let build = std::env::var("VOCALKEEP_BUILD_NUMBER")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "dev".into());
    let sha = std::env::var("VOCALKEEP_GIT_SHA")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .or_else(|| {
            Command::new("git")
                .args(["rev-parse", "HEAD"])
                .output()
                .ok()
                .filter(|o| o.status.success())
                .and_then(|o| String::from_utf8(o.stdout).ok())
        })
        .map(|s| s.trim().chars().take(12).collect::<String>())
        .unwrap_or_else(|| "unknown".into());
    let date = std::env::var("SOURCE_DATE_EPOCH")
        .ok()
        .and_then(|s| s.parse::<i64>().ok())
        .and_then(chrono_free_date)
        .unwrap_or_else(|| {
            Command::new("date")
                .args(["-u", "+%Y-%m-%d"])
                .output()
                .ok()
                .filter(|o| o.status.success())
                .and_then(|o| String::from_utf8(o.stdout).ok())
                .map(|s| s.trim().to_string())
                .unwrap_or_else(|| "unknown".into())
        });

    println!("cargo:rustc-env=VOCALKEEP_BUILD_NUMBER={build}");
    println!("cargo:rustc-env=VOCALKEEP_GIT_SHA={sha}");
    println!("cargo:rustc-env=VOCALKEEP_BUILD_DATE={date}");
}

/// Converts Unix seconds to YYYY-MM-DD without pulling a date crate into the build script.
fn chrono_free_date(secs: i64) -> Option<String> {
    let days = secs.div_euclid(86_400);
    // Civil-from-days (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    Some(format!("{y:04}-{m:02}-{d:02}"))
}
