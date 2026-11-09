# Using your voice

A finished voice is a folder with a Piper voice model (`<id>.onnx`), its settings
(`<id>.onnx.json`), a `MODEL_CARD` and Vocalkeep's `voice.json`. From **My voice** in the app (or
`vocalkeep package` and `vocalkeep install`) it can be packaged for each of the places below.

| Where | How | Format |
| --- | --- | --- |
| [Saywell](https://github.com/lobojoel2003/Saywell) (Android AAC) | Copy the file to the device, then **Settings › Saywell voices › Install from a file** | `vits-piper-<id>.tar.bz2` |
| Android, every app | Install **SherpaTTS** ([F-Droid](https://f-droid.org/packages/org.woheller69.ttsengine/), [source](https://github.com/woheller69/ttsEngine)), then **Manage languages › Install from SD card** | `<id>-sherpatts.zip` |
| Linux, every app | `vocalkeep install <voice> --target linux` adds it to speech-dispatcher (Orca, Firefox, `spd-say`) | installed directly |
| Windows, every app | Install [VoiceGarden](https://github.com/AACTools/VoiceGarden-SAPI), then `vocalkeep install <voice> --target windows` and **Install to SAPI** in VoiceGarden | `<id>-windows-sapi.zip` |
| NVDA screen reader | The [Sonata](https://github.com/mush42/sonata-nvda) add-on: **Voice manager › Install from local file** | `<id>.tar.gz` |
| macOS and iPhone | The **Piper Neural TTS** app ([source](https://github.com/piper-tts-apps/piper-app-apple)): import the `.onnx` and `.onnx.json` | `<id>.tar.gz` |
| Android, Piper app | **Piper for Android** ([source](https://github.com/piper-tts-apps/piper-app-android)): import the `.onnx` and `.onnx.json` | `<id>.tar.gz` |
| Home Assistant, Piper on the command line | Copy the `.onnx` and `.onnx.json` | `<id>.tar.gz` |

## Saywell

Saywell runs Piper voices with Sherpa-ONNX, completely offline.

1. In Vocalkeep, **My voice › Saywell › Save files** (or `vocalkeep package <voice> --format saywell -o .`).
2. Copy `vits-piper-<id>.tar.bz2` to the phone or tablet (USB cable, a memory card, or a cloud drive).
3. In Saywell: **Settings › Saywell voices › Install from a file**, and pick the file.
4. Choose your voice in the same screen. Saywell shows its model card, including the licence.

## Android system voice (SherpaTTS)

SherpaTTS makes a Sherpa-ONNX voice the phone's text-to-speech engine, so any app that speaks
(TalkBack, AAC apps, e-book readers) can use it.

1. Save **Android system voice** files and unzip `<id>-sherpatts.zip` on the phone.
2. In SherpaTTS: **Manage languages › Install from SD card**.
3. Enter the 3-letter language code (`eng` for English), a name, then pick `model.onnx` and then
   `tokens.txt`.
4. In Android **Settings › Accessibility › Text-to-speech output**, choose SherpaTTS.

SherpaTTS holds one voice per language. The zip also contains a `HOW-TO-INSTALL.txt` with an
alternative that uses a computer and `adb`.

> SherpaTTS's author notes that Google's developer-verification rules may stop apps from
> outside the Play Store installing on certified Android devices from 2026–27. Saywell and
> SherpaTTS are both affected; check their pages for current advice.

## Linux

```bash
vocalkeep install ~/.local/share/io.github.lobojoel2003.vocalkeep/voices/en_US-jane-medium --target linux
spd-say -o vocalkeep-generic "Hello, this is my voice."
```

This copies the voice to `~/.local/share/vocalkeep/voices/`, writes a small `vocalkeep-speak`
helper and a speech-dispatcher module (`~/.config/speech-dispatcher/modules/vocalkeep-generic.conf`).
Add `--make-default` to make it the default voice for every app. Nothing needs root.
`vocalkeep uninstall <id> --target linux` removes it again.

## Windows

Windows apps (and AAC software such as Grid) use SAPI 5 voices. The open-source
[VoiceGarden](https://github.com/AACTools/VoiceGarden-SAPI) engine runs Sherpa-ONNX voices as SAPI
voices.

1. Install VoiceGarden.
2. `vocalkeep install <voice> --target windows` (or **My voice › This computer › Install**) copies
   your voice into VoiceGarden's models folder.
3. Open VoiceGarden and choose **Install to SAPI** (it asks for administrator rights once).

The Windows zip also contains an experimental `register-sapi.reg` for advanced users; prefer
VoiceGarden's own button.

## NVDA

The Sonata add-on runs Piper voices inside NVDA. In NVDA, open **Sonata voice manager › Installed
› Install from local file** and choose `<id>.tar.gz`. Sonata hasn't yet been updated for the 64-bit
NVDA 2026.1; check the add-on's page before relying on it.

## Trying the voice

In **My voice**, type something and press **Say it**, or:

```bash
vocalkeep speak path/to/en_US-jane-medium "Hello, it's me." -o hello.wav
```
