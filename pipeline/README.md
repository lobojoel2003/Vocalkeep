# Vocalkeep training pipeline

This turns a voice bank recorded in the Vocalkeep app into **your own voice**: a Piper
text-to-speech voice that sounds like you. Then it installs that voice where you need it: on
Linux, Windows, Android, in NVDA, on a Mac, or in the Saywell AAC app.

The desktop app runs these commands for you. You only need this page if you want to do it by
hand, or train on another computer (one with a graphics card).

Everything runs on your own computers. Nothing is uploaded. The only download is the "starting
voice" that training begins from.

## What you need

* Python 3.10 or newer.
* For **speaking and packaging** voices: any computer.
* For **training**: a computer with an NVIDIA graphics card (8 GB of memory or more) is best.
  Training takes hours there. On an ordinary processor it takes days.

## Install

From the Vocalkeep source folder:

```sh
pip install "./pipeline[runtime]"
```

Or from a release wheel:

```sh
pip install "vocalkeep-0.1.0-py3-none-any.whl[runtime]"
```

`[runtime]` adds Piper's runtime (`piper-tts`). It lets Vocalkeep speak with voices and gives
the voice packages the espeak-ng data they need. Without it, you can still prepare recordings.

Check what your computer can do:

```sh
vocalkeep doctor
```

It says, in plain words, what to install next.

## Training on a computer with a graphics card

Training uses Piper's own training code from
[piper1-gpl](https://github.com/OHF-voice/piper1-gpl). It isn't on PyPI in a form that can
train, so install it from its source, with the same Python that runs Vocalkeep:

```sh
sudo apt-get install build-essential cmake ninja-build    # Debian or Ubuntu
git clone https://github.com/OHF-voice/piper1-gpl.git
cd piper1-gpl
python3 -m pip install -e '.[train]'
./build_monotonic_align.sh
```

If Piper later complains about `espeakbridge`, also run `python3 setup.py build_ext --inplace`
in that folder. Then run `vocalkeep doctor` again: it should say "Can train voices: yes".

If Piper's training tools live in a different Python (for example their own virtual
environment), pass it with `--python /path/to/that/python` to `train`, `export` and `build`.

## The whole thing in one go

```sh
vocalkeep build "My voice bank" --base ljspeech -o ~/Voices
```

This prepares the recordings, downloads the starting voice, trains, and makes the voice in
`~/Voices/en_US-jane-medium/` (the name comes from your voice bank).

* `--quick` trains a short preview (150 epochs) so you can hear how it is going.
* `--epochs N` chooses how long to train (default: 1000 epochs on top of the starting voice).
* `--work DIR` keeps the prepared recordings and the training run in `DIR` (by default a
  folder for this bank in Vocalkeep's cache, `~/.cache/vocalkeep/work/`). If training is
  interrupted, run the same command again: it carries on from where it stopped. Downloaded
  starting voices are kept in `~/.cache/vocalkeep/checkpoints/` and reused.
* `--dry-run` shows what would happen, without training.
* `--progress json` prints progress as JSON lines (this is what the desktop app uses).

## Step by step

```sh
# 1. Check the recordings again (it never trusts the stored results)
vocalkeep check "My voice bank"

# 2. Prepare them for training: 22050 Hz, trimmed, level-matched
vocalkeep prepare "My voice bank" -o dataset

# 3. Train, starting from a base voice
vocalkeep train dataset --base ljspeech -o run

# 4. Make the finished voice
vocalkeep export run -o ~/Voices

# 5. Listen
vocalkeep speak ~/Voices/en_US-jane-medium "Hello, this is my voice." -o hello.wav
```

A voice bank can be the bank folder, or a backup `.zip` made by the Vocalkeep app.

`prepare` leaves out recordings marked "redo", missing files and recordings without text.
`dataset.json` lists what was left out and why. Use `--min-verdict good` to keep only the best
recordings.

About how many sentences you need: around 100 gives a rough preview, 300 a recognisable voice,
and 600 or more a natural one.

### How long to train

`train` passes Piper's `--ckpt_path`, which carries on the starting voice's epoch count. So
Vocalkeep reads how far the starting voice was trained and adds your epochs to it. For
example, lessac is at epoch 2164, so 1000 more epochs means training until epoch 3164. Piper's
guide uses about 1000 to 2000 extra epochs for small fine-tunes.

## Starting voices and licences

A new voice is fine-tuned from an existing Piper voice. **The licence of that voice's
recordings decides what your voice may be used for.** Piper adds no licence of its own.

See them all with `vocalkeep bases` (or `vocalkeep bases --commercial`).

| Starting voice | Language | Recordings | Commercial use |
|---|---|---|---|
| **ljspeech** (recommended) | US English | LJ Speech, public domain | yes |
| **kristin** (recommended) | US English | LibriVox, public domain | yes |
| **cori** (recommended) | British English | LibriVox, public domain | yes |
| john | US English | LibriVox, public domain (fine-tuned from kristin) | yes |
| bryce | US English | public domain, but built on an unreleased voice | unclear |
| lessac | US English | Blizzard 2013, research only | **no** |
| almost all others | | fine-tuned from lessac | **no** |

**The lessac problem.** Most of Piper's medium voices (amy, joe, ryan, alba, jenny_dioco,
northern_english_male, libritts_r, vctk and others) were fine-tuned from lessac. Lessac's
recordings are licensed for research only, so every voice built on it is not for commercial
use, even when its own recordings are public domain or CC BY. Vocalkeep's recommended starting
voices were trained from scratch on public domain recordings, so they have no such limits.

`--require-commercial` makes `train` and `build` refuse starting voices that aren't cleared for
commercial use.

Whatever the starting voice, the voice you make is your voice. Its `MODEL_CARD` says so, and
says what it may be used for.

## Using your voice

```sh
vocalkeep package ~/Voices/en_US-jane-medium --format all -o packages
```

| Format | File | Where it works |
|---|---|---|
| `piper` | `en_US-jane-medium.tar.gz` | Piper, Home Assistant, Piper for Android, the macOS "Piper Neural TTS" app |
| `nvda` | the same file | NVDA with the Sonata add-on |
| `sherpa` | `vits-piper-en_US-jane-medium.tar.bz2` | apps built on Sherpa-ONNX |
| `saywell` | the same file | the Saywell AAC app |
| `sherpatts` | `en_US-jane-medium-sherpatts.zip` | Android system voice, with SherpaTTS |
| `voicegarden` | `en_US-jane-medium-windows-sapi.zip` | Windows SAPI 5 voice, with VoiceGarden |

Every package includes the `MODEL_CARD`. The Android and Windows packages have a
`HOW-TO-INSTALL.txt` inside.

### Linux (Speech Dispatcher: Orca, Firefox, GNOME, KDE)

```sh
vocalkeep install ~/Voices/en_US-jane-medium --target linux
killall speech-dispatcher        # it starts again by itself
spd-say -o vocalkeep-generic "Hello, this is my voice."
```

This needs no administrator rights. It copies the voice to `~/.local/share/vocalkeep/voices/`,
writes a small speaking script, and adds a Speech Dispatcher module
(`~/.config/speech-dispatcher/modules/vocalkeep-generic.conf`). Add `--make-default` to make it
the voice everything uses. `vocalkeep uninstall en_US-jane-medium --target linux` removes it
again, including any lines added to your `speechd.conf`.

### Windows

1. Install [VoiceGarden](https://github.com/AACTools/VoiceGarden-SAPI/releases).
2. Run `vocalkeep install VOICE --target windows` (or unzip the `voicegarden` package into
   `%LOCALAPPDATA%\VoiceGardenSAPIAdapter\models\`).
3. In VoiceGarden, click **Install to SAPI** for the voice.

The package also has a `register-sapi.reg`. It is advanced and experimental: it writes the
same registry keys VoiceGarden does, but it hasn't been tested end to end. Use VoiceGarden's
button instead if you can.

### Android, Saywell, NVDA and Mac

`vocalkeep install VOICE --target saywell` (or `android`, `nvda`, `macos`) prints step-by-step
instructions: which package to make, and where to tap or click.

* **Saywell**: Settings › Saywell voices › Install from a file, and choose the `saywell`
  package.
* **Android**: install SherpaTTS from F-Droid, then Manage Languages › Install from SD Card, and
  choose `model.onnx` and `tokens.txt` from the `sherpatts` package.
* **NVDA**: install the Sonata add-on and install the `nvda` package from it. (Sonata hadn't
  been updated for NVDA 2026.1 when this was written; the Windows SAPI voice works too.)
* **Mac**: import the `.onnx` and `.onnx.json` from the `piper` package into "Piper Neural TTS".

## For developers

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e "pipeline[dev]"
cd pipeline
ruff check . && ruff format --check . && mypy && pytest
python3 ../scripts/sync-shared.py --check   # the packaged quality.json matches shared/
```

The quality checker (`src/vocalkeep/quality.py`) is the same algorithm as the desktop app's
(`crates/vocalkeep-core/src/quality.rs`), with the same thresholds (`shared/quality.json`).
Both are tested against `shared/fixtures/`. Change them together.

An optional test speaks with a real voice:
`VOCALKEEP_TEST_VOICE=/path/to/voice-folder-or.onnx pytest -m integration`.

Licence: GPL-3.0-or-later.
