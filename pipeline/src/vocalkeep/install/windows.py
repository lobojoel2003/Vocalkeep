# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing a voice for Windows programs (SAPI 5) through VoiceGarden.

VoiceGarden (https://github.com/AACTools/VoiceGarden-SAPI, MIT licence) is a SAPI 5 engine that
runs Sherpa-ONNX models. It looks for models in
``%LOCALAPPDATA%\\VoiceGardenSAPIAdapter\\models\\<id>\\`` (``model.onnx``, ``tokens.txt``,
``espeak-ng-data\\``). Vocalkeep copies the voice there; the person then clicks
"Install to SAPI" in VoiceGarden, which registers it with Windows (that step needs
administrator rights, which Vocalkeep never asks for).

A ``register-sapi.reg`` with the real paths is written next to the model as an advanced,
experimental alternative. It is not applied.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from vocalkeep.errors import VocalkeepError
from vocalkeep.espeak import find_espeak_data
from vocalkeep.package import sapi_reg, voicegarden_instructions
from vocalkeep.paths import local_app_data
from vocalkeep.progress import NullReporter, Reporter
from vocalkeep.sherpa import add_metadata, sherpa_metadata, write_tokens
from vocalkeep.voice import Voice

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass
class WindowsResult:
    voice_id: str
    folder: Path
    actions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def models_dir() -> Path:
    base = local_app_data()
    if base is None:
        raise VocalkeepError(
            "This doesn't look like Windows: LOCALAPPDATA isn't set.",
            "To prepare the voice for a Windows computer, run "
            "'vocalkeep package VOICE --format voicegarden -o FOLDER' and follow "
            "HOW-TO-INSTALL.txt inside the zip on that computer.",
        )
    return base / "VoiceGardenSAPIAdapter" / "models"


def install_windows(
    voice: Voice,
    *,
    dry_run: bool = False,
    espeak_data: str | Path | None = None,
    reporter: Reporter | None = None,
) -> WindowsResult:
    reporter = reporter or NullReporter()
    if not _SAFE_ID.match(voice.id):
        raise VocalkeepError(f"The voice id '{voice.id}' has characters that can't be used here.")
    target = models_dir() / voice.id
    result = WindowsResult(voice.id, target)
    data = find_espeak_data(espeak_data)
    if data is None:
        raise VocalkeepError(
            "The Windows voice needs espeak-ng's data, and none was found.",
            "Install Piper's runtime (pip install 'vocalkeep[runtime]'), or pass --espeak-data.",
        )
    result.actions += [
        f"copy the voice (model.onnx, tokens.txt, espeak-ng-data) to {target}",
        f"write {target / 'register-sapi.reg'} (experimental, not applied)",
    ]
    result.next_steps += [
        "Install VoiceGarden if you haven't: https://github.com/AACTools/VoiceGarden-SAPI/releases",
        f"Open VoiceGarden, find the voice '{voice.id}' and click 'Install to SAPI'. "
        "Windows asks for permission; say yes.",
        "Helpers can instead run as administrator:  VoiceGarden.UI.exe models promote-all",
        "Then choose the voice in your AAC or reading program (it is listed with the Windows "
        "SAPI 5 voices).",
    ]
    if dry_run:
        return result

    staging = target.with_name(f".{voice.id}.installing")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    reporter.log("Adding the details Sherpa-ONNX needs to the model")
    add_metadata(voice.onnx, staging / "model.onnx", sherpa_metadata(voice.config, voice.language))
    write_tokens(voice.config, staging / "tokens.txt")
    shutil.copytree(data, staging / "espeak-ng-data")
    (staging / "MODEL_CARD").write_text(voice.model_card_text, encoding="utf-8")
    (staging / "HOW-TO-INSTALL.txt").write_text(
        voicegarden_instructions(voice), encoding="utf-8", newline="\r\n"
    )
    (staging / "register-sapi.reg").write_bytes(sapi_reg(voice, str(target)).encode("utf-16"))
    shutil.rmtree(target, ignore_errors=True)
    staging.replace(target)
    reporter.log(f"Copied the voice to {target}")
    return result


def uninstall_windows(voice_id: str, reporter: Reporter | None = None) -> WindowsResult:
    reporter = reporter or NullReporter()
    if not _SAFE_ID.match(voice_id):
        raise VocalkeepError(f"'{voice_id}' isn't a voice id.")
    target = models_dir() / voice_id
    result = WindowsResult(voice_id, target)
    if not target.is_dir():
        raise VocalkeepError(f"The voice {voice_id} isn't in VoiceGarden's models folder.")
    result.next_steps.append(
        "If you installed it to SAPI, first click 'Remove from SAPI' in VoiceGarden (or it "
        "stays listed in Windows without working)."
    )
    shutil.rmtree(target)
    result.actions.append(f"removed {target}")
    return result
