# Voice bank format (version 1)

A Vocalkeep voice bank is an ordinary folder. Nothing is hidden in a database, so the recordings
stay usable with or without Vocalkeep, today and in twenty years.

```text
My voice bank/
├── bank.json                          everything about the recordings (below)
├── bank.json.bak                      the previous save, used if bank.json is ever damaged
├── recordings/
│   ├── arctic-en/arctic_a0001.wav     one kept take per sentence
│   ├── everyday-en/everyday-0042.wav
│   ├── phrases-en/phrases-0007.wav
│   └── personal/personal-0001.wav     the person's own phrases
├── legacy/
│   └── 4d0c…e1.wav                    legacy messages, kept exactly as said
└── pending/                           takes not yet kept or discarded (safe to delete)
```

## Audio

- **WAV, 16-bit PCM, mono**, at the microphone's own sample rate (usually 48 000 or 44 100 Hz).
  The training pipeline resamples to 22 050 Hz itself, so nothing is lost by recording higher.
- Each sentence keeps only its latest take. Re-recording replaces the file and increases
  `attempts`.

## `bank.json`

UTF-8 JSON with camelCase keys. Saved atomically: written to `bank.json.tmp`, the old file copied
to `bank.json.bak`, then renamed into place.

| Field | Meaning |
| --- | --- |
| `format` | Always `"vocalkeep-bank"` |
| `version` | Format version, `1`. Newer versions are refused by older apps rather than misread. |
| `id` | A random UUID identifying this bank |
| `createdAt`, `updatedAt` | RFC 3339 UTC timestamps |
| `appVersion` | Vocalkeep version that last saved the bank |
| `speaker` | `{ name, language, gender? }`. `language` is a BCP 47 tag such as `en-US`; `gender` (`female`, `male`, `neutral`) only labels the finished voice in system voice lists |
| `room` | The last room check: `{ level, noiseFloorDbfs, peakDbfs, sampleRate, checkedAt }` |
| `takes[]` | One per recorded sentence (below) |
| `sessions[]` | `{ id, startedAt, endedAt?, energy, kept, retried, speechMs }` |
| `customPrompts[]` | The person's own phrases: `{ id, text, createdAt }` |
| `legacy[]` | Legacy messages (below) |

### Takes

```json
{
  "promptId": "everyday-0042",
  "setId": "everyday-en",
  "text": "Shall we watch the match together on Saturday?",
  "file": "recordings/everyday-en/everyday-0042.wav",
  "sampleRate": 48000,
  "durationMs": 3420,
  "recordedAt": "2026-11-08T15:12:09Z",
  "sessionId": "1f3c…",
  "attempts": 2,
  "quality": {
    "verdict": "good",
    "issues": [],
    "sampleRate": 48000,
    "durationMs": 3420,
    "peakDbfs": -5.8,
    "speechDbfs": -21.2,
    "noiseFloorDbfs": -64.1,
    "snrDb": 42.9,
    "clippedSamples": 0,
    "clipRuns": 0,
    "dcOffset": 0.0003,
    "speechStartMs": 420,
    "speechEndMs": 3060,
    "speechMs": 2380,
    "longestPauseMs": 260
  }
}
```

`text` is stored with every take, so the bank stays meaningful even if a future version of
Vocalkeep changes its sentence lists. `file` is always relative, with `/` separators; readers must
refuse paths that are absolute or contain `..`.

`verdict` is `good`, `okay` (fine to keep, with a note) or `redo` (kept anyway even though another
try was suggested; the pipeline leaves these out). Issue codes and their thresholds are described
in [quality-checks.md](quality-checks.md).

### Legacy messages

```json
{
  "id": "4d0c…e1",
  "title": "Happy 18th birthday",
  "recipient": "Leo",
  "occasion": "Birthday",
  "recordedBy": "Maya",
  "note": "For the morning of your eighteenth.",
  "file": "legacy/4d0c…e1.wav",
  "sampleRate": 48000,
  "durationMs": 124000,
  "recordedAt": "2026-11-07T18:02:44Z"
}
```

Legacy messages are never used for training.

## Backups

**Settings › Voice bank › Back up** writes a zip with one top-level folder
(`Vocalkeep voice bank - <name>/`) containing `bank.json` and every referenced WAV file. Audio is
stored uncompressed in the zip. The training pipeline reads these zips directly
(`vocalkeep build "My voice bank.zip" …`), and **Restore a backup** unpacks one into an empty
folder, checking every path.

## Exported legacy messages

**Messages › Save all to a folder** writes `Legacy messages from <name>/` with:

- `01 - Happy 18th birthday (for Leo).wav` and so on, in the order they were recorded;
- `index.html`, a small page that plays every message in any web browser, offline;
- `messages.json` (`"format": "vocalkeep-legacy-messages"`) with the same details;
- `README.txt`.
