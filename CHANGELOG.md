# Changelog

All notable changes to Vocalkeep are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Each build also has a build number (the CI run
number), shown in Settings › About.

## [Unreleased]

## [0.1.1] - 2026-11-09

### Fixed

- **Six starting voices could not be downloaded.** Piper renamed the checkpoints for Cori, Amy,
  Joe, Alba, Jenny (Dioco) and HFC female in its repository, so building a voice on them stopped
  with "error 404". The links and their training epochs are updated.

### Changed

- **The voice builder follows renamed checkpoints.** If a starting voice's file has moved, it
  downloads the replacement from the same folder and says so, instead of stopping.
- **The weekly starting-voice check** now tells moved checkpoints (a warning, with an issue
  opened that shows the exact fix, and `--fix` to apply it) apart from missing ones (a failure),
  and retries once before calling a server unreachable.
- CI no longer runs twice for Dependabot updates.

## [0.1.0] - 2026-11-09

First release: a free, open-source way to bank your own voice, from recording to a system voice.

### Added

- **A calm recording studio** (Windows, macOS, Linux). One sentence at a time in large type, a
  big record button and full keyboard control (Space, Enter, R, L, S). A daily check-in
  ("How does your voice feel today?") sizes each session: strong, okay or tired. Tired days get
  a few short sentences. Water-break reminders, a gentle "good place to stop", and a session
  summary that celebrates milestones. No streaks, no guilt.
- **Quality checks on every take**, with kind, specific tips: clipping, too quiet or loud,
  background noise, signal-to-noise, words cut off at the start or end, long pauses, speaking
  rate against the sentence, DC offset. A room check measures background noise before the first
  session. The microphone keeps recording 300 ms after Stop so last words aren't cut.
- **1,631 built-in sentences**: 1,081 sound-rich sentences from CMU ARCTIC (51 left out for
  distressing themes or dated language), 400 everyday conversation sentences and 150 short
  phrases written for Vocalkeep (CC0), plus the person's own phrases (names, places, sayings).
  Sessions mix the sets so a voice learns every sound and natural conversational rhythm.
- **A progress view that fills up as the voice takes shape**: a ring of spokes that grows with
  every kept sentence, milestones from "First words" to "Complete", speech sounds and sound pairs
  covered (via eSpeak NG phonemes, as Piper uses), per-set progress and the last two weeks.
- **Legacy messages**: record birthday wishes, advice and stories exactly as said (up to
  15 minutes each), for whom, the occasion and who recorded them; family members can record too.
  Export them as plain WAV files with an offline web page that plays them anywhere.
- **The voice builder** (`vocalkeep`, Python): re-checks and prepares recordings, fine-tunes an
  open Piper voice with piper1-gpl, exports ONNX, and packages or installs it for Saywell,
  Android (SherpaTTS), Windows (VoiceGarden SAPI), Linux (speech-dispatcher), NVDA (Sonata) and
  Piper apps on macOS, iPhone and Android. The app runs it with live progress.
- **Licence-aware starting voices**: every Piper starting voice is listed with its dataset licence
  and whether commercial use is allowed (most descend from the research-only "lessac" voice).
  Public-domain voices trained from scratch are recommended; `--require-commercial` enforces it.
- **Your data stays yours**: no account, no network access in the app, a plain-folder voice bank
  saved atomically with a recovery copy, zip backups and safe restores.
- **Accessibility**: Atkinson Hyperlegible Next, four text sizes, light, dark and yellow-on-black
  high-contrast themes, reduced motion, screen-reader labels throughout.
- **Releases**: one version in `VERSION` for every component, build numbers from CI, installers
  for Linux (`.deb`, `.rpm`, AppImage), Windows (`.msi`, `.exe`) and macOS (`.dmg`), the voice
  builder as a Python wheel, SHA-256 checksums, and CI on every push.

[Unreleased]: https://github.com/lobojoel2003/Vocalkeep/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/lobojoel2003/Vocalkeep/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lobojoel2003/Vocalkeep/releases/tag/v0.1.0
