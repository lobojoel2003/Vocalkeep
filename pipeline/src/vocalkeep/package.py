# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice packages for each place a voice can be used.

========== ================================ ==============================================
Format     File                             Where it works
========== ================================ ==============================================
piper      ``<id>.tar.gz``                  Piper itself, Home Assistant, the macOS "Piper
                                            Neural TTS" app, "Piper for Android" (unpack:
                                            ``.onnx`` + ``.onnx.json``)
nvda       ``<id>.tar.gz`` (same file)      NVDA with the Sonata add-on
sherpa     ``vits-piper-<id>.tar.bz2``      Anything built on Sherpa-ONNX
saywell    ``vits-piper-<id>.tar.bz2``      The Saywell AAC app (same file as sherpa)
sherpatts  ``<id>-sherpatts.zip``           Android system voice with SherpaTTS
voicegarden ``<id>-windows-sapi.zip``       Windows SAPI 5 voice with VoiceGarden
========== ================================ ==============================================

Every package carries the voice's ``MODEL_CARD``.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

from vocalkeep.errors import VocalkeepError
from vocalkeep.espeak import find_espeak_data
from vocalkeep.languages import iso639_3, normalize_tag, windows_langid
from vocalkeep.progress import NullReporter, Reporter
from vocalkeep.sherpa import add_metadata, sherpa_metadata, write_tokens
from vocalkeep.voice import Voice

FORMATS = ("piper", "nvda", "sherpa", "saywell", "sherpatts", "voicegarden")
SAPI_CLSID = "{013AB33B-AD1A-401C-8BEE-F6E2B046A94E}"
SAPI_TOKENS = r"SOFTWARE\Microsoft\Speech\Voices\Tokens"
ONECORE_TOKENS = r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
VOICEGARDEN_MODELS = r"%LOCALAPPDATA%\VoiceGardenSAPIAdapter\models"
SHERPATTS_DIR = "modelDir"


def package_file_name(voice_id: str, fmt: str) -> str:
    """The file a format produces."""
    if fmt in ("piper", "nvda"):
        return f"{voice_id}.tar.gz"
    if fmt in ("sherpa", "saywell"):
        return f"vits-piper-{voice_id}.tar.bz2"
    if fmt == "sherpatts":
        return f"{voice_id}-sherpatts.zip"
    if fmt == "voicegarden":
        return f"{voice_id}-windows-sapi.zip"
    raise VocalkeepError(f"Unknown package format '{fmt}'. Choose one of: {', '.join(FORMATS)}.")


def expand_formats(formats: Iterable[str]) -> list[str]:
    """``all`` → every format. Formats that make the same file are kept once."""
    result: list[str] = []
    seen_files: set[str] = set()
    for fmt in formats:
        for f in FORMATS if fmt == "all" else (fmt,):
            if f not in FORMATS:
                raise VocalkeepError(
                    f"Unknown package format '{f}'.",
                    f"Choose one of: {', '.join(FORMATS)}, or all.",
                )
            key = package_file_name("x", f)
            if key not in seen_files:
                seen_files.add(key)
                result.append(f)
    return result


def sapi_gender(gender: str | None) -> str:
    g = (gender or "").lower()
    if g in ("female", "woman", "f"):
        return "Female"
    if g in ("male", "man", "m"):
        return "Male"
    return "Neutral"


def _reg_path(path: str) -> str:
    return path.replace("\\", "\\\\")


def sapi_reg(voice: Voice, model_dir: str) -> str:
    """An (experimental) ``.reg`` file registering the voice with SAPI the way VoiceGarden does.

    ``model_dir`` is the Windows folder holding ``model.onnx``.
    """
    voice_id = voice.id
    token = f"Sherpa-{voice_id}"
    friendly = f"Sherpa {voice_id}"
    locale = normalize_tag(voice.language)
    langid = windows_langid(locale)
    gender = sapi_gender(voice.gender)
    model = _reg_path(model_dir.rstrip("\\") + r"\model.onnx")
    tokens = _reg_path(model_dir.rstrip("\\") + r"\tokens.txt")
    data = _reg_path(model_dir.rstrip("\\") + r"\espeak-ng-data")
    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        "; ADVANCED / EXPERIMENTAL - most people should NOT use this file.",
        "; The normal way is VoiceGarden's 'Install to SAPI' button (see HOW-TO-INSTALL.txt).",
        ";",
        "; This file registers the voice directly, using the same registry keys VoiceGarden",
        "; writes. It has not been tested end to end by the Vocalkeep project. It needs",
        "; VoiceGarden installed (it provides the speech engine) and administrator rights.",
        ";",
        "; Before using it, check that every path below points at the folder where you put the",
        "; voice. If you see YOUR-USER-NAME, replace it with your Windows user name.",
        ";",
        f"; To remove the voice later, delete the keys named {token} under",
        f";   HKEY_LOCAL_MACHINE\\{SAPI_TOKENS}",
        f";   HKEY_LOCAL_MACHINE\\{ONECORE_TOKENS}",
        "",
    ]
    for root, with_type in ((SAPI_TOKENS, True), (ONECORE_TOKENS, False)):
        key = f"HKEY_LOCAL_MACHINE\\{root}\\{token}"
        lines += [
            f"[{key}]",
            f'@="{friendly}"',
            f'"CLSID"="{SAPI_CLSID}"',
            "",
            f"[{key}\\VoiceGardenConfig]",
            '"EngineType"="Sherpa"',
            '"SherpaOnnxModelType"=dword:00000000',
            f'"SherpaOnnxModelPath"="{model}"',
            f'"SherpaOnnxTokens"="{tokens}"',
            f'"SherpaOnnxDataDir"="{data}"',
            "",
            f"[{key}\\Attributes]",
            f'"Name"="{voice_id}"',
            f'"Gender"="{gender}"',
            '"Age"="Adult"',
            f'"Language"="{langid}"',
            f'"Locale"="{locale}"',
            '"Vendor"="K2FSA"',
        ]
        if with_type:
            lines.append('"VoiceGardenType"="Sherpa;Offline"')
        lines += ['"Quality"="medium"', ""]
    return "\r\n".join(lines) + "\r\n"


def sherpatts_instructions(voice: Voice) -> str:
    code = iso639_3(voice.language)
    return f"""How to use {voice.name}'s voice on Android with SherpaTTS
{"=" * (40 + len(voice.name))}

SherpaTTS is a free text-to-speech engine for Android. Once this voice is in it, apps that
talk (AAC apps, screen readers, book readers) can speak with it.

Before you start
1. Install SherpaTTS from F-Droid (search for "SherpaTTS"; its package name is
   org.woheller69.ttsengine) or from https://github.com/woheller69/ttsEngine/releases
2. Unzip this file. You get a folder called "{SHERPATTS_DIR}" with model.onnx, tokens.txt,
   lang and MODEL_CARD in it. If you unzipped it on a computer, copy that folder to the
   phone (for example into Downloads).

Method 1: on the phone (easiest)
3. Open SherpaTTS and tap "Manage Languages".
4. Tap "Install from SD Card".
5. Type the language code:  {code}
6. Type a name for the voice, for example:  {voice.name}
7. When it asks for the model file, choose model.onnx from the {SHERPATTS_DIR} folder.
8. When it asks for the tokens file, choose tokens.txt from the same folder.

Method 2: with a computer and ADB (for helpers)
   adb push {SHERPATTS_DIR} /sdcard/Android/data/org.woheller69.ttsengine/files/
   Then close SherpaTTS completely and open it again. It reads the "lang" file
   (line 1: language code, line 2: name) and adds the voice by itself.
   Newer versions of SherpaTTS may no longer do this. If nothing happens, use Method 1.

Make it the phone's voice
9. Open the phone's Settings and search for "Text-to-speech output" (it is usually under
   System > Languages, or Accessibility).
10. Choose SherpaTTS as the preferred engine, then choose this voice in SherpaTTS.

Good to know
- SherpaTTS keeps one voice per language. Installing this voice replaces any other
  voice for the same language in SherpaTTS.
- The voice works offline. Nothing you type is sent anywhere.
- MODEL_CARD says whose voice this is and what it may be used for.
"""


def voicegarden_instructions(voice: Voice) -> str:
    return f"""How to use {voice.name}'s voice on Windows
{"=" * (27 + len(voice.name))}

Windows programs speak with "SAPI 5" voices. VoiceGarden (free, open source) lets Windows
use Piper voices like this one.

1. Install VoiceGarden from https://github.com/AACTools/VoiceGarden-SAPI/releases
2. Unzip this file. You get a folder called "{voice.id}".
3. Copy that folder into this folder:
       {VOICEGARDEN_MODELS}
   Tip: paste that line into the address bar of File Explorer and press Enter. If the
   "models" folder doesn't exist yet, create it.
   (On a computer with Vocalkeep, 'vocalkeep install VOICE --target windows' does this
   step for you.)
4. Open VoiceGarden. The voice "{voice.id}" appears in the list of offline voices.
5. Click "Install to SAPI" for it. Windows asks for permission; say yes.
   Helpers can instead run this as administrator:
       VoiceGarden.UI.exe models promote-all
6. The voice now appears in programs that use Windows voices, such as AAC software,
   Balabolka, and NVDA's "Microsoft Speech API version 5" synthesizer.

Good to know
- The voice works offline. Nothing you type is sent anywhere.
- To remove it, use VoiceGarden's "Remove from SAPI", then delete the folder.
- MODEL_CARD says whose voice this is and what it may be used for.

Advanced (experimental): register-sapi.reg
   This file registers the voice with SAPI directly, using the registry keys VoiceGarden
   writes. It is NOT needed if you use step 5, and it has not been tested end to end.
   Open it in Notepad first: replace YOUR-USER-NAME in the paths with your Windows user
   name, check the paths, then double-click it (needs administrator rights).
"""


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if info.isdir() else 0o644
    return info


def _write_tar(out: Path, members: list[tuple[Path, str]], mode: str) -> None:
    part = out.with_name(out.name + ".part")
    with tarfile.open(part, mode) as tar:  # type: ignore[call-overload]
        for src, arcname in members:
            tar.add(src, arcname=arcname, recursive=True, filter=_tar_filter)
    part.replace(out)


def _write_zip(out: Path, members: list[tuple[Path, str]]) -> None:
    part = out.with_name(out.name + ".part")
    with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, arcname in members:
            if src.is_dir():
                for dirpath, dirnames, filenames in os.walk(src):
                    dirnames.sort()
                    for name in sorted(filenames):
                        file = Path(dirpath) / name
                        rel = file.relative_to(src).as_posix()
                        z.write(file, f"{arcname}/{rel}")
            else:
                z.write(src, arcname)
    part.replace(out)


class Packager:
    """Builds packages for one voice. Shared pieces (the Sherpa model) are made once."""

    def __init__(
        self,
        voice: Voice,
        out_dir: Path,
        espeak_data: str | Path | None = None,
        reporter: Reporter | None = None,
    ) -> None:
        self.voice = voice
        self.out_dir = Path(out_dir).expanduser()
        self.reporter = reporter or NullReporter()
        self.espeak_data = find_espeak_data(espeak_data)
        self._tmp = Path(tempfile.mkdtemp(prefix="vocalkeep-package-"))
        self._sherpa_model: Path | None = None
        self._tokens: Path | None = None
        self._card: Path | None = None

    def close(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def __enter__(self) -> Packager:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # Shared pieces -----------------------------------------------------------------------

    @property
    def model_card(self) -> Path:
        if self._card is None:
            self._card = self._tmp / "MODEL_CARD"
            self._card.write_text(self.voice.model_card_text, encoding="utf-8")
        return self._card

    @property
    def sherpa_model(self) -> Path:
        if self._sherpa_model is None:
            self.reporter.log("Adding the details Sherpa-ONNX needs to the model")
            self._sherpa_model = self._tmp / "sherpa" / f"{self.voice.id}.onnx"
            add_metadata(
                self.voice.onnx,
                self._sherpa_model,
                sherpa_metadata(self.voice.config, self.voice.language),
            )
        return self._sherpa_model

    @property
    def tokens(self) -> Path:
        if self._tokens is None:
            self._tokens = self._tmp / "tokens.txt"
            write_tokens(self.voice.config, self._tokens)
        return self._tokens

    # Formats -----------------------------------------------------------------------------

    def build(self, fmt: str) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = self.out_dir / package_file_name(self.voice.id, fmt)
        if fmt in ("piper", "nvda"):
            self._piper(out)
        elif fmt in ("sherpa", "saywell"):
            self._sherpa(out)
        elif fmt == "sherpatts":
            self._sherpatts(out)
        elif fmt == "voicegarden":
            self._voicegarden(out)
        else:  # pragma: no cover - package_file_name rejects unknown formats first
            raise VocalkeepError(f"Unknown package format '{fmt}'.")
        return out

    def _piper(self, out: Path) -> None:
        v = self.voice
        # Files at the root: Sonata (NVDA) wants *.onnx, *.json and MODEL_CARD side by side,
        # and takes the first *.json it finds as the config, so voice.json stays out.
        _write_tar(
            out,
            [
                (v.onnx, f"{v.id}.onnx"),
                (v.config_path, f"{v.id}.onnx.json"),
                (self.model_card, "MODEL_CARD"),
            ],
            "w:gz",
        )

    def _sherpa(self, out: Path) -> None:
        v = self.voice
        folder = f"vits-piper-{v.id}"
        root = self._tmp / folder
        root.mkdir(exist_ok=True)
        members = [
            (root, folder),
        ]
        # Directory entry first, then the files inside it.
        files = [
            (self.sherpa_model, f"{folder}/{v.id}.onnx"),
            (v.config_path, f"{folder}/{v.id}.onnx.json"),
            (self.tokens, f"{folder}/tokens.txt"),
            (self.model_card, f"{folder}/MODEL_CARD"),
        ]
        if self.espeak_data:
            files.append((self.espeak_data, f"{folder}/espeak-ng-data"))
        else:
            self.reporter.warn(
                "No espeak-ng data was found, so the package doesn't include it. Saywell and "
                "SherpaTTS bring their own, so it still works there. For other Sherpa-ONNX apps, "
                "install piper-tts (pip install 'vocalkeep[runtime]') or pass --espeak-data."
            )
        part = out.with_name(out.name + ".part")
        with tarfile.open(part, "w:bz2") as tar:
            tar.add(members[0][0], arcname=members[0][1], recursive=False, filter=_tar_filter)
            for src, arcname in files:
                tar.add(src, arcname=arcname, recursive=True, filter=_tar_filter)
        part.replace(out)

    def _sherpatts(self, out: Path) -> None:
        v = self.voice
        lang = self._tmp / "lang"
        lang.write_text(f"{iso639_3(v.language)}\n{v.name}\n", encoding="utf-8", newline="\n")
        howto = self._tmp / "HOW-TO-INSTALL-sherpatts.txt"
        howto.write_text(sherpatts_instructions(v), encoding="utf-8", newline="\r\n")
        _write_zip(
            out,
            [
                (self.sherpa_model, f"{SHERPATTS_DIR}/model.onnx"),
                (self.tokens, f"{SHERPATTS_DIR}/tokens.txt"),
                (lang, f"{SHERPATTS_DIR}/lang"),
                (self.model_card, f"{SHERPATTS_DIR}/MODEL_CARD"),
                (howto, "HOW-TO-INSTALL.txt"),
            ],
        )

    def _voicegarden(self, out: Path) -> None:
        v = self.voice
        if not self.espeak_data:
            raise VocalkeepError(
                "The Windows package needs espeak-ng's data, and none was found.",
                "Install Piper's runtime (pip install 'vocalkeep[runtime]'), or pass "
                "--espeak-data with the path of an espeak-ng-data folder.",
            )
        howto = self._tmp / "HOW-TO-INSTALL-windows.txt"
        howto.write_text(voicegarden_instructions(v), encoding="utf-8", newline="\r\n")
        reg = self._tmp / "register-sapi.reg"
        model_dir = rf"C:\Users\YOUR-USER-NAME\AppData\Local\VoiceGardenSAPIAdapter\models\{v.id}"
        # .reg files are read as UTF-16 when they start with a BOM; that is the safe choice.
        reg.write_bytes(sapi_reg(v, model_dir).encode("utf-16"))
        _write_zip(
            out,
            [
                (self.sherpa_model, f"{v.id}/model.onnx"),
                (self.tokens, f"{v.id}/tokens.txt"),
                (self.espeak_data, f"{v.id}/espeak-ng-data"),
                (self.model_card, f"{v.id}/MODEL_CARD"),
                (howto, "HOW-TO-INSTALL.txt"),
                (reg, "register-sapi.reg"),
            ],
        )


def package_voice(
    voice: Voice,
    formats: Iterable[str],
    out_dir: str | Path,
    *,
    espeak_data: str | Path | None = None,
    reporter: Reporter | None = None,
) -> list[Path]:
    """Builds the requested packages. Returns the files made, in order.

    With ``all``, a Windows package that can't be made (no espeak-ng data) is skipped with a
    note instead of stopping the others.
    """
    reporter = reporter or NullReporter()
    requested = list(formats)
    wanted = expand_formats(requested)
    made: list[Path] = []
    with Packager(voice, Path(out_dir), espeak_data, reporter) as packager:
        for i, fmt in enumerate(wanted):
            reporter.progress("package", i / len(wanted), f"Making the {fmt} package")
            if fmt == "voicegarden" and "all" in requested and packager.espeak_data is None:
                reporter.warn(
                    "Skipped the Windows package: it needs espeak-ng data. Install "
                    "'vocalkeep[runtime]' or pass --espeak-data."
                )
                continue
            made.append(packager.build(fmt))
        reporter.progress("package", 1.0, "Packages ready")
    return made
