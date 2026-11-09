# Releasing

Vocalkeep uses [Semantic Versioning](https://semver.org/). The single source of the version is
[`VERSION`](../VERSION); every manifest is kept equal to it, and CI checks that they agree.

| What | Where it comes from |
| --- | --- |
| Version (`0.1.0`) | `VERSION`, copied into `Cargo.toml`, `desktop/package.json`, `tauri.conf.json`, `pipeline/pyproject.toml` and `vocalkeep/__init__.py` |
| Tag (`v0.1.0`) | `v` + `VERSION`; the release workflow refuses a tag that doesn't match |
| Build number | The GitHub Actions run number (`VOCALKEEP_BUILD_NUMBER`); local builds say `dev` |
| Commit | `VOCALKEEP_GIT_SHA`, or `git rev-parse HEAD` for local builds |

The app shows all of these in **Settings › About** ("Version 0.1.0 · build 42 · 1a2b3c4d5e6f").
macOS bundles also carry the build number as `CFBundleVersion`.

## Making a release

1. Bump the version everywhere:

   ```bash
   ./scripts/bump-version.sh 0.2.0
   ```

2. Move the `## [Unreleased]` notes in [`CHANGELOG.md`](../CHANGELOG.md) under a new
   `## [0.2.0] - YYYY-MM-DD` heading and update the links at the bottom.

3. Commit, then either push a tag:

   ```bash
   git commit -am "chore: release 0.2.0"
   git push origin main
   git tag -a v0.2.0 -m "Vocalkeep 0.2.0"
   git push origin v0.2.0
   ```

   or, on GitHub, open **Actions › Release › Run workflow** on `main` and tick **publish**. The
   workflow creates the tag with the release. Leave **publish** unticked to build the installers
   without releasing (a dry run).

## What the release workflow does

1. Runs the full CI (versions, Rust on three platforms, interface, pipeline on Python 3.10–3.13).
2. Checks that the tag matches `VERSION` and that `CHANGELOG.md` has a section for it.
3. Builds the app with Tauri: `.deb`, `.rpm` and AppImage on Linux, `.msi` and `-setup.exe` on
   Windows, `.dmg` on macOS (Apple silicon).
4. Builds the voice builder's wheel and source distribution and smoke-tests the wheel.
5. Publishes a GitHub Release with the changelog section as notes, a download table, every file,
   and `SHA256SUMS.txt`. Versions with a suffix (`1.0.0-beta.1`) are marked as pre-releases.

## Code signing

The installers are not code-signed yet. Windows SmartScreen may show "Windows protected your PC"
(choose **More info › Run anyway**), and macOS may need **right-click › Open** the first time.
Signing can be added to the `desktop` job with Tauri's signing environment variables once
certificates are available.
