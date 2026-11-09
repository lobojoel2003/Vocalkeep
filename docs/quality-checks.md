# Recording quality checks

Every take is checked the moment it's recorded, so problems are fixed while the person is still at
the microphone, not discovered weeks later during training. The checks are tuned for tired voices:
anything that only *might* matter is a gentle note (**okay**), and only problems that would hurt
the trained voice suggest another try (**redo**). The person can always keep a take anyway.

The same algorithm runs in two places with the same thresholds,
[`shared/quality.json`](../shared/quality.json):

- in the app, in Rust ([`crates/vocalkeep-core/src/quality.rs`](../crates/vocalkeep-core/src/quality.rs));
- in the voice builder, in Python ([`pipeline/src/vocalkeep/quality.py`](../pipeline/src/vocalkeep/quality.py)),
  which re-checks every recording from the audio before training.

[`shared/fixtures/`](../shared/fixtures) holds synthetic recordings with the verdict each must get.
Both test suites check them, so the two implementations can't drift apart.

## How a take is measured

1. The DC offset (average sample value) is measured and removed.
2. **Clipping** is counted on the raw signal: samples at or above 0.995 of full scale, and *runs*
   of two or more such samples (a flattened, crackling peak).
3. The take is cut into 20 ms frames and each frame's level is measured.
4. The **background** (noise floor) is the average power of the quietest tenth of frames.
5. A frame counts as **speech** if it is at least 10 dB above the background (and above
   −60 dBFS). Runs shorter than 60 ms are ignored, so a click or a tap isn't mistaken for speech.
6. **Speech level** is the average power of speech frames; **signal-to-noise** is speech level
   minus background.

## What is reported

| Code | Shown as | Severity | When |
| --- | --- | --- | --- |
| `no-speech` | We didn't hear anything | redo | no speech frames at all |
| `too-short` | That was very short | redo | under 250 ms of speech |
| `clipping` | A little too loud | redo | any run of clipped samples |
| `near-clipping` | Close to too loud | note | isolated clipped samples, or a peak above −0.5 dBFS |
| `too-quiet` | A little quiet | note / redo | speech below −30 dBFS / below −40 dBFS |
| `too-loud` | Quite loud | note | speech above −9 dBFS (without clipping) |
| `noisy` | Background noise | note / redo | background above −50 dBFS / above −38 dBFS |
| `low-snr` | Your voice is close to the background | note / redo | below 25 dB / below 15 dB (only when neither of the two above explains it) |
| `cut-off-start` | It may have started early | note | speech in the first 40 ms |
| `cut-off-end` | The end may be cut off | redo | speech in the last 40 ms (the app keeps recording 300 ms after Stop, so this means the person was still talking) |
| `long-pause` | A long pause | note | a silence over 2.5 s inside the sentence |
| `too-fast` | Some words may be missing | note | more than 28 letters per second of speech for the sentence |
| `too-slow` | Longer than expected | note | fewer than 3 letters per second |
| `dc-offset` | The microphone signal is offset | note | average sample value above 0.02 |

The verdict is **redo** if any issue is a redo, **okay** if there are only notes, and **good**
otherwise.

Legacy messages are checked more lightly: only `no-speech`, `clipping`, `too-quiet` and `noisy`
are reported, because a message is kept exactly as said, pauses and all.

## The room check

Four seconds of silence (the first half second is skipped). The median frame level decides:

| Level | Background |
| --- | --- |
| Beautifully quiet | −60 dBFS or lower |
| Quiet enough | up to −50 dBFS |
| A bit of background noise | up to −40 dBFS |
| Quite noisy | above −40 dBFS |

## Before training

The voice builder re-checks every take from the audio (it doesn't trust the stored verdict), leaves
out `redo` takes, trims each take to its speech plus 120 ms either side, and evens out loudness to
about −20 dBFS of speech with peaks kept below −1 dBFS.
