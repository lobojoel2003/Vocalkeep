# Licences: starting voices and other voice-cloning models

Vocalkeep builds a person's voice by fine-tuning an existing open
[Piper](https://github.com/OHF-Voice/piper1-gpl) voice (the *starting voice*) on their recordings.
The starting voice's training data comes with a licence, and **that licence carries over to the
finished voice**. Piper itself adds no licence to its voices; the datasets' licences govern
([maintainer's note](https://github.com/rhasspy/piper/discussions/271)).

For a person's own communication, almost any starting voice is fine. It matters if the voice might
ever be used commercially, for example by a company, in a paid product, or by a service that
charges for it. **Vocalkeep recommends starting voices trained from scratch on public-domain
recordings**, and shows every voice's licence before training. `vocalkeep train --require-commercial`
refuses any starting voice that isn't clearly free for commercial use.

> This page summarises licences as published by their authors (checked November 2026). It is not
> legal advice. Each voice's `MODEL_CARD` is the source of truth.

## The catch: most Piper voices descend from "lessac"

Many of Piper's medium-quality voices were not trained from scratch: they were *fine-tuned from
the `lessac` voice*. Lessac was trained on the Blizzard Challenge 2013 Lessac data, which is
**licensed for research only, with commercial use explicitly excluded**. A voice fine-tuned from
lessac inherits that restriction, even when its own recordings are public domain or CC BY.

## Starting voices Vocalkeep knows

Model cards: [rhasspy/piper-samples](https://github.com/rhasspy/piper-samples/tree/master/samples/en)
(mirrors of the cards on Hugging Face). Checkpoints: [rhasspy/piper-checkpoints](https://huggingface.co/datasets/rhasspy/piper-checkpoints).

### Recommended: trained from scratch on public-domain audio

| Voice | Language | Recordings | Licence | Commercial use |
| --- | --- | --- | --- | --- |
| **ljspeech** (medium) | US English | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | Public domain | Yes |
| **kristin** (medium) | US English | LibriVox | Public domain | Yes |
| **cori** (medium) | UK English | LibriVox | Public domain | Yes |
| john (medium) | US English | LibriVox, fine-tuned from kristin | Public domain | Yes |

### Not for commercial use

| Voice | Recordings | Licence | Why |
| --- | --- | --- | --- |
| lessac | Blizzard 2013 Lessac | Research only | Commercial use excluded |
| ryan | RyanSpeech | CC BY-NC-SA 4.0 | Non-commercial (and a lessac fine-tune) |
| hfc_female, hfc_male | Hi-Fi-CAPTAIN | CC BY-NC-SA 4.0 | Non-commercial (and lessac fine-tunes) |
| l2arctic | L2-ARCTIC | CC BY-NC 4.0 | Non-commercial (and a lessac fine-tune) |
| semaine (UK) | SEMAINE | CC BY-NC-SA 4.0 | Non-commercial (and a lessac fine-tune) |
| alan (UK) | Mycroft mimic3 | "All rights reserved" | No licence granted |
| libritts_r, joe, arctic, alba, aru, vctk, northern_english_male, jenny_dioco | Permissive datasets (CC BY 4.0, CC0, CC BY-SA 4.0, …) | Dataset is permissive | **Fine-tuned from lessac**, so research only |
| amy, kusal | Card says "see URL" | Unclear | Lessac fine-tunes with unclear dataset licences |
| bryce | The creator's own voice, released as public domain | Public domain | Fine-tuned from an unreleased voice whose licence isn't published, so Vocalkeep lists it as unclear |

`vocalkeep bases` prints this list with sources; `vocalkeep bases --commercial` shows only voices
that are free for any use.

## Your recordings and your voice

The recordings in a voice bank belong to the person who made them. Vocalkeep's sentence lists
are free to use: the everyday sentences and short phrases are written for Vocalkeep and released
under CC0, and the sound-rich sentences come from
[CMU ARCTIC](http://www.festvox.org/cmu_arctic/) under a permissive licence
([text](../shared/prompts/LICENSES/CMU-ARCTIC.txt)); Vocalkeep left 51 of its 1,132 sentences out
(violence, illness and dated language) and changed nothing else.

The finished voice's `MODEL_CARD` records whose voice it is, the starting voice, and its licence.

## Other voice-cloning models, and why Vocalkeep doesn't use them

People often ask about "zero-shot" cloning models that copy a voice from a few seconds of audio.
Several are excellent, but many forbid commercial use, need a powerful GPU just to speak, or can't
run offline on a phone. Piper voices run in real time on a phone or an old laptop, which is what
an AAC user needs every day.

| Model | Code | Weights | Commercial use |
| --- | --- | --- | --- |
| Coqui XTTS-v2 | MPL-2.0 | Coqui Public Model License (non-commercial); Coqui has shut down | No |
| F5-TTS | MIT | CC BY-NC (Emilia training data) | No |
| E2-TTS (community weights) | — | CC BY-NC 4.0 | No |
| Spark-TTS | Apache-2.0 | CC BY-NC-SA 4.0 | No |
| Fish Speech / OpenAudio | Fish Audio Community License | Same; research and non-commercial, small businesses under a revenue cap | Limited |
| StyleTTS 2 | MIT | Custom terms: disclose synthetic speech unless the speaker consented | With conditions |
| IndexTTS 2 | bilibili Model Use License | Same | Yes, below usage thresholds |
| OpenVoice v2 | MIT | MIT | Yes |
| Kokoro-82M | Apache-2.0 | Apache-2.0 | Yes (not designed for cloning) |
| Chatterbox | MIT | MIT, with a built-in watermark; retired in 2026 | Yes |
| Dia, Zonos, MetaVoice-1B, Bark | Apache-2.0 / MIT | Apache-2.0 / MIT | Yes |
| Orpheus | Apache-2.0 | Built on Llama 3.2, whose licence terms apply | With conditions |
| CosyVoice 2, Parler-TTS | Apache-2.0 | Reported as Apache-2.0 | Check before use |

Sources: each project's repository and model card, for example
[F5-TTS](https://github.com/SWivid/F5-TTS), [Fish Speech](https://github.com/fishaudio/fish-speech),
[StyleTTS 2](https://github.com/yl4579/StyleTTS2), [OpenVoice](https://github.com/myshell-ai/OpenVoice),
[Kokoro](https://github.com/hexgrad/kokoro), [Chatterbox](https://github.com/resemble-ai/chatterbox),
[IndexTTS](https://github.com/index-tts/index-tts/blob/main/LICENSE). Licences change; check the
current terms before relying on any of them.
