//! Version, build number and commit of this build.

use serde::Serialize;

/// Semantic version from the workspace manifest (kept equal to `VERSION`).
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// CI run number, or `dev` for local builds.
pub const BUILD_NUMBER: &str = env!("VOCALKEEP_BUILD_NUMBER");
/// Short commit hash, or `unknown`.
pub const GIT_SHA: &str = env!("VOCALKEEP_GIT_SHA");
/// UTC build date (YYYY-MM-DD).
pub const BUILD_DATE: &str = env!("VOCALKEEP_BUILD_DATE");

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BuildInfo {
    pub version: &'static str,
    pub build_number: &'static str,
    pub git_sha: &'static str,
    pub build_date: &'static str,
}

pub fn build_info() -> BuildInfo {
    BuildInfo {
        version: VERSION,
        build_number: BUILD_NUMBER,
        git_sha: GIT_SHA,
        build_date: BUILD_DATE,
    }
}

/// "0.1.0 (build 42, 1a2b3c4d5e6f)"
pub fn long_version() -> String {
    format!("{VERSION} (build {BUILD_NUMBER}, {GIT_SHA})")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_is_semver() {
        let parts: Vec<_> = VERSION.split(['.', '-']).collect();
        assert!(parts.len() >= 3, "{VERSION}");
        assert!(
            parts[..3].iter().all(|p| p.parse::<u32>().is_ok()),
            "{VERSION}"
        );
    }

    #[test]
    fn long_version_mentions_build() {
        assert!(long_version().contains("build"));
        assert!(!BUILD_NUMBER.is_empty());
        assert_eq!(BUILD_DATE.len(), 10, "{BUILD_DATE}");
    }
}
