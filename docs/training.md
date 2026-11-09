# Building the voice

The voice builder (`vocalkeep`, in [`pipeline/`](../pipeline)) turns a voice bank into a Piper
voice. It fine-tunes an open starting voice on the person's recordings with
[piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) and exports the result to ONNX, the format
Piper apps, Saywell and Sherpa-ONNX run.

```text
voice bank ──prepare──▶ dataset ──train──▶ checkpoint ──export──▶ voice ──package──▶ Saywell, Android, …
 (48 kHz WAV,            (22.05 kHz,         (PyTorch,             (.onnx +
  bank.json)              metadata.csv)       on a GPU)             .onnx.json)
```

## What you need

- A computer with an **NVIDIA graphics card** (8 GB of video memory or more is comfortable) running
  Linux or Windows (WSL works). Training on a CPU works but takes days.
- Python 3.10 to 3.13.
- About 10 GB of free disk space.

It doesn't have to be the computer used for recording. A family member, a friend, a speech
therapist's clinic or a rented cloud GPU can build the voice from a backup zip.

## Install

```bash
# 1. The voice builder, with the Piper runtime for trying and installing voices
python3 -m venv ~/.local/share/vocalkeep/venv
source ~/.local/share/vocalkeep/venv/bin/activate
pip install "./pipeline[runtime]"        # from a clone of this repository, or the release wheel

# 2. Piper's training code (not on PyPI)
sudo apt install build-essential cmake ninja-build      # or your system's equivalent
git clone https://github.com/OHF-Voice/piper1-gpl.git
cd piper1-gpl
pip install -e '.[train]'
./build_monotonic_align.sh
cd ..

# 3. Check everything
vocalkeep doctor
```

`vocalkeep doctor` says, in plain words, what is missing. The Vocalkeep app finds the builder
automatically if it's on the `PATH`, in `~/.local/bin`, or in `~/.local/share/vocalkeep/venv`
(otherwise set its path in **Settings › Voice builder**).

## Build

From the app: **My voice › Build my voice**. Or on the command line:

```bash
vocalkeep build "Maya voice bank.zip" --base en_GB-cori-medium -o voices
```

`build` runs these steps, which can also be run one at a time:

```bash
vocalkeep prepare "Maya voice bank.zip" -o work/dataset        # check, trim, level, resample
vocalkeep train work/dataset --base en_GB-cori-medium -o work/run
vocalkeep export work/run -o voices --name Maya
```

- `--quick` builds a short preview (about 150 extra training epochs) to hear how things are going.
- `--epochs N` sets the extra epochs for a full voice (default 1000).
- `--dry-run` prints the training command without running it.
- `--progress json` prints machine-readable progress (the app uses this).

### How long it takes

Piper continues training from the starting voice's checkpoint. Time depends on the GPU and the
number of recordings; as a rough guide, a preview takes about an hour and a full voice from 600
sentences takes several hours on a mid-range card. Training can be stopped and started again.

## How many sentences?

Piper doesn't publish a minimum. Voices have been fine-tuned successfully from about an hour of
speech (roughly 1,000 sentences), and fine-tuning from a good starting voice works with less.
Vocalkeep's milestones are guidance:

| Sentences | Milestone | What to expect |
| --- | --- | --- |
| 10 | First words | The microphone and room are working |
| 100 | A first sketch | A rough preview, to hear the idea |
| 300 | Recognisably you | A preview starts to sound like the person |
| **600** | **Natural** | **Suggested point to build an everyday voice** |
| 1,000 | Rich and expressive | Smoother and more expressive |
| 1,500 | Complete | Most built-in sentences recorded |

More recordings help, and so does variety: Vocalkeep mixes sound-rich sentences (which cover
every English sound quickly), everyday conversation (for natural rhythm, questions and
exclamations), short phrases, and the person's own phrases. The **Progress** page shows how many of
English's speech sounds and sound pairs are covered.

### If a starting voice moves

Piper reorganises its checkpoint repository from time to time. If the file Vocalkeep knows
about has been renamed, the builder looks in the same folder, downloads the replacement and
tells you it did. A weekly check in this repository (`scripts/check_base_links.py`) keeps the
list up to date.

## Choosing a starting voice

Choose a starting voice in the same language variety, and ideally a similar pitch. Its licence
carries over to the finished voice: see [licences.md](licences.md). Vocalkeep recommends
`en_US-ljspeech-medium`, `en_US-kristin-medium` or `en_GB-cori-medium`, which were trained from
scratch on public-domain recordings.

## What the builder does to the recordings

`prepare` re-checks every take from the audio with the same checks the app uses
([quality-checks.md](quality-checks.md)), leaves out takes worth redoing, trims each take to the
speech plus 120 ms, evens out loudness, resamples to 22,050 Hz mono and writes Piper's
`metadata.csv` (`<id>.wav|text`). `dataset.json` lists every take that was left out and why.
