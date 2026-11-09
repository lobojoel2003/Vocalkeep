# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing a voice as a Linux system voice through Speech Dispatcher.

Speech Dispatcher is what Linux desktops (Orca, Firefox, GNOME, KDE) use to speak. It has no
Piper module in its released versions, so Vocalkeep installs a small "generic" module:

``~/.local/share/vocalkeep/voices/<id>/``
    a copy of the voice.
``~/.local/share/vocalkeep/bin/vocalkeep-speak``
    a script that reads text on standard input, runs Piper with *this* Python
    (``python -m piper --output-raw``) and plays the sound with ``paplay``, ``pw-play`` or
    ``aplay`` (whichever was found at install time).
``~/.config/speech-dispatcher/modules/vocalkeep-generic.conf``
    tells Speech Dispatcher's ``sd_generic`` how to call that script. When no ``AddModule``
    line is active, Speech Dispatcher loads every ``*-generic.conf`` in that folder by itself.

If the person's ``speechd.conf`` lists modules explicitly, an ``AddModule`` line is added for
ours; ``--make-default`` also sets ``DefaultModule``. Lines Vocalkeep adds are marked so
``vocalkeep uninstall`` can remove them. Nothing here needs administrator rights.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from vocalkeep import __version__
from vocalkeep.errors import VocalkeepError
from vocalkeep.languages import base_language
from vocalkeep.paths import xdg_config_home, xdg_data_home
from vocalkeep.progress import NullReporter, Reporter
from vocalkeep.voice import Voice, load_voice

MODULE_NAME = "vocalkeep-generic"
MARKER = "# Added by Vocalkeep; 'vocalkeep uninstall' removes it."
DISABLED_PREFIX = "#vocalkeep-disabled: "
SYSTEM_SPEECHD_CONF = Path("/etc/speech-dispatcher/speechd.conf")
#: Speech Dispatcher rates (-100…100) map to Piper's length scale as 3 ** (-rate / 100):
#: rate 100 is three times as fast, -100 three times as slow, 0 unchanged.
RATE_RANGE = 3.0

_ACTIVE_ADD_MODULE = re.compile(r"^\s*AddModule\s", re.IGNORECASE)
_ACTIVE_DEFAULT = re.compile(r"^\s*DefaultModule\s", re.IGNORECASE)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Player:
    """How the wrapper plays raw 16-bit mono audio."""

    name: str
    #: Shell command; ``$sample_rate`` is filled in by the wrapper.
    command: str


#: In order of preference. paplay and aplay also work on PipeWire systems (through its
#: PulseAudio and ALSA layers).
PLAYERS = (
    Player("paplay", 'paplay --raw --rate="$sample_rate" --format=s16le --channels=1'),
    Player("aplay", 'aplay -q -r "$sample_rate" -f S16_LE -t raw -c 1 -'),
    # pw-play needs --raw for headerless audio (PipeWire 1.0 and later).
    Player("pw-play", 'pw-play --raw --rate="$sample_rate" --channels=1 --format=s16 -'),
)


def find_player() -> Player | None:
    for player in PLAYERS:
        if shutil.which(player.name):
            return player
    return None


@dataclass(frozen=True)
class LinuxPaths:
    data: Path
    voices: Path
    bin_dir: Path
    wrapper: Path
    speechd_dir: Path
    modules_dir: Path
    module_conf: Path
    speechd_conf: Path
    state: Path

    @staticmethod
    def current() -> LinuxPaths:
        data = xdg_data_home() / "vocalkeep"
        speechd = xdg_config_home() / "speech-dispatcher"
        return LinuxPaths(
            data=data,
            voices=data / "voices",
            bin_dir=data / "bin",
            wrapper=data / "bin" / "vocalkeep-speak",
            speechd_dir=speechd,
            modules_dir=speechd / "modules",
            module_conf=speechd / "modules" / f"{MODULE_NAME}.conf",
            speechd_conf=speechd / "speechd.conf",
            state=data / "linux-install.json",
        )


@dataclass
class InstalledVoice:
    id: str
    model: Path
    sample_rate: int
    language: str
    gender: str | None


@dataclass
class LinuxResult:
    voice_id: str
    actions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _installed(paths: LinuxPaths) -> list[InstalledVoice]:
    voices: list[InstalledVoice] = []
    if not paths.voices.is_dir():
        return voices
    for folder in sorted(paths.voices.iterdir()):
        if not folder.is_dir():
            continue
        try:
            v = load_voice(folder)
        except VocalkeepError:
            continue
        voices.append(InstalledVoice(v.id, v.onnx, v.sample_rate, v.language, v.gender))
    return voices


def _read_state(paths: LinuxPaths) -> dict[str, str]:
    try:
        data = json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(paths: LinuxPaths, state: dict[str, str]) -> None:
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    paths.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def wrapper_script(
    voices: list[InstalledVoice], default_id: str, player: Player | None, python: str
) -> str:
    """The ``vocalkeep-speak`` shell script."""
    cases = "\n".join(
        f"    {_shell_quote(v.id)}) model={_shell_quote(str(v.model))}; "
        f"sample_rate={int(v.sample_rate)} ;;"
        for v in voices
    )
    if player:
        play = player.command
        player_note = f"# Audio player found at install time: {player.name}"
    else:
        play = (
            'echo "vocalkeep-speak: no audio player (paplay, aplay or pw-play) was found" >&2; '
            "exit 1"
        )
        player_note = "# No audio player was found at install time; set VOCALKEEP_PLAYER."
    return f"""#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# vocalkeep-speak: reads text on standard input and speaks it with a Vocalkeep voice.
#
# Written by 'vocalkeep install' (Vocalkeep {__version__}). It is rewritten whenever a voice
# is installed or removed, so changes made here don't last.
#
# Usage: vocalkeep-speak [VOICE_ID] [RATE] < text
#   VOICE_ID  an installed voice (default: {default_id})
#   RATE      Speech Dispatcher rate, -100 (slowest) to 100 (fastest); 0 is normal speed
# Set VOCALKEEP_PLAYER to a shell command to play the raw 16-bit mono sound differently
# (its sample rate is in $VOCALKEEP_RATE), for example: VOCALKEEP_PLAYER='cat > out.raw'
{player_note}

PYTHON={_shell_quote(python)}
DEFAULT_VOICE={_shell_quote(default_id)}

voice="${{1:-$DEFAULT_VOICE}}"
rate="${{2:-0}}"

select_voice() {{
  case "$1" in
{cases}
    *) return 1 ;;
  esac
}}

if ! select_voice "$voice"; then
  if ! select_voice "$DEFAULT_VOICE"; then
    echo "vocalkeep-speak: no Vocalkeep voice is installed" >&2
    exit 1
  fi
fi

# Speech Dispatcher's rate to Piper's length scale ({RATE_RANGE:g} ** (-rate / 100)).
length_scale=1
if command -v awk >/dev/null 2>&1; then
  length_scale=$(awk -v r="$rate" 'BEGIN {{
    if (r + 0 != r) r = 0
    if (r < -100) r = -100
    if (r > 100) r = 100
    printf "%.3f", exp(-r / 100 * log({RATE_RANGE:g}))
  }}')
fi

play() {{
  if [ -n "${{VOCALKEEP_PLAYER:-}}" ]; then
    VOCALKEEP_RATE="$sample_rate" sh -c "$VOCALKEEP_PLAYER"
  else
    {play}
  fi
}}

"$PYTHON" -m piper -m "$model" --output-raw --length-scale "$length_scale" | play
"""


def module_conf(voices: list[InstalledVoice], default_id: str, wrapper: Path) -> str:
    """``vocalkeep-generic.conf`` for Speech Dispatcher's sd_generic."""
    wrapper_str = str(wrapper)
    if "'" in wrapper_str or '"' in wrapper_str or "\\" in wrapper_str:
        raise VocalkeepError(
            f"The install folder {wrapper.parent} has a quote or backslash in its name, "
            "which Speech Dispatcher can't handle.",
            "Set XDG_DATA_HOME to a folder without such characters and install again.",
        )
    languages: list[str] = []
    for v in voices:
        lang = base_language(v.language)
        if lang not in languages:
            languages.append(lang)
    voice_lines: list[str] = []
    counters: dict[tuple[str, str], int] = {}
    for v in voices:
        lang = base_language(v.language)
        kinds = {"female": ["FEMALE"], "male": ["MALE"]}.get(v.gender or "", ["FEMALE", "MALE"])
        for kind in kinds:
            n = counters.get((lang, kind), 0) + 1
            counters[(lang, kind)] = n
            if n <= 3:
                voice_lines.append(f'AddVoice "{lang}" "{kind}{n}" "{v.id}"')
    language_lines = "\n".join(f'GenericLanguage "{lang}" "{lang}" "utf-8"' for lang in languages)
    return f"""# SPDX-License-Identifier: GPL-3.0-or-later
# Speech Dispatcher module for Vocalkeep voices (Piper), written by 'vocalkeep install'
# (Vocalkeep {__version__}). It is rewritten whenever a voice is installed or removed.
#
# Test it with:  spd-say -o {MODULE_NAME} "Hello, this is my voice."
# Speech Dispatcher loads *-generic.conf files from this folder by itself unless speechd.conf
# lists modules with AddModule; then this line is needed there:
#   AddModule "{MODULE_NAME}" "sd_generic" "{MODULE_NAME}.conf"

Debug 0

# $DATA is the text (single quotes already escaped by Speech Dispatcher), $VOICE the voice
# id below and $RATE the speaking rate from -100 to 100.
GenericExecuteSynth "printf %s \\'$DATA\\' | \\'{wrapper_str}\\' \\'$VOICE\\' \\'$RATE\\'"
# (No GenericCmdDependency: older Speech Dispatcher releases don't know that option, and the
# script always exists while this file does.)
GenericDefaultCharset "utf-8"
{language_lines}

# Pass the rate through unchanged (-100..100) as a whole number; the script turns it into
# Piper's length scale. (Multiply is given in hundredths: 100 means 1.0.)
GenericRateAdd 0
GenericRateMultiply 100
GenericRateForceInteger 1

# Piper splits sentences itself, so send longer pieces of text at a time.
GenericMaxChunkLength 2000
GenericDelimiters ".?!"

{chr(10).join(voice_lines)}
DefaultVoice "{default_id}"
"""


def _strip_ours(lines: list[str]) -> list[str]:
    """Removes lines Vocalkeep added and re-enables lines it disabled."""
    out: list[str] = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.rstrip("\n") == MARKER:
            skip_next = True
            continue
        if line.startswith(DISABLED_PREFIX):
            out.append(line[len(DISABLED_PREFIX) :])
            continue
        out.append(line)
    return out


def _has_active(lines: list[str], pattern: re.Pattern[str]) -> bool:
    return any(pattern.match(line) for line in lines)


def update_speechd_conf(
    paths: LinuxPaths,
    *,
    want_module: bool,
    make_default: bool,
    language: str | None,
    system_conf: Path | None = None,
) -> list[str]:
    """Adds (or, with ``want_module=False``, removes) our lines in the user's speechd.conf.

    Returns what was done, in words. The user's file is only created when it must be: to set the
    default module, or because the system file lists modules explicitly (which turns off
    automatic loading of our module).
    """
    actions: list[str] = []
    system_conf = system_conf or SYSTEM_SPEECHD_CONF
    conf = paths.speechd_conf
    existing = conf.read_text(encoding="utf-8").splitlines(keepends=True) if conf.is_file() else []
    lines = _strip_ours(existing)
    changed = lines != existing

    if want_module:
        effective = lines
        if not conf.is_file() and system_conf.is_file():
            effective = system_conf.read_text(encoding="utf-8").splitlines(keepends=True)
        needs_add_module = _has_active(effective, _ACTIVE_ADD_MODULE)
        if (needs_add_module or make_default) and not conf.is_file():
            # The user's file replaces the system one, so start from a copy of it.
            lines = list(effective)
            actions.append(f"created {conf} from the system settings")
            changed = True
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if needs_add_module:
            lines += [
                MARKER + "\n",
                f'AddModule "{MODULE_NAME}" "sd_generic" "{MODULE_NAME}.conf"\n',
            ]
            actions.append(f"added an AddModule line for {MODULE_NAME} to {conf}")
            changed = True
        if make_default:
            lines = [
                DISABLED_PREFIX + line if _ACTIVE_DEFAULT.match(line) else line for line in lines
            ]
            lines += [MARKER + "\n", f"DefaultModule {MODULE_NAME}\n"]
            if language:
                lines += [
                    MARKER + "\n",
                    f'LanguageDefaultModule "{base_language(language)}" "{MODULE_NAME}"\n',
                ]
            actions.append(f"made {MODULE_NAME} the default voice module in {conf}")
            changed = True
    elif changed:
        actions.append(f"removed Vocalkeep's lines from {conf}")

    if changed:
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text("".join(lines), encoding="utf-8")
    return actions


def _write_files(
    paths: LinuxPaths, voices: list[InstalledVoice], default_id: str, python: str
) -> None:
    player = find_player()
    paths.bin_dir.mkdir(parents=True, exist_ok=True)
    paths.wrapper.write_text(
        wrapper_script(voices, default_id, player, python), encoding="utf-8", newline="\n"
    )
    mode = paths.wrapper.stat().st_mode
    paths.wrapper.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    paths.modules_dir.mkdir(parents=True, exist_ok=True)
    paths.module_conf.write_text(
        module_conf(voices, default_id, paths.wrapper), encoding="utf-8", newline="\n"
    )


def _check_runtime() -> str | None:
    import importlib.util

    if importlib.util.find_spec("piper") is None:
        return (
            "Piper's runtime isn't installed for this Python, so the voice can't speak yet. "
            "Install it with: pip install 'vocalkeep[runtime]' (or: pip install piper-tts)."
        )
    return None


def install_linux(
    voice: Voice,
    *,
    make_default: bool = False,
    dry_run: bool = False,
    reporter: Reporter | None = None,
    python: str | None = None,
) -> LinuxResult:
    reporter = reporter or NullReporter()
    if not _SAFE_ID.match(voice.id):
        raise VocalkeepError(f"The voice id '{voice.id}' has characters that can't be used here.")
    paths = LinuxPaths.current()
    python = python or sys.executable
    result = LinuxResult(voice.id)
    target = paths.voices / voice.id
    player = find_player()

    result.actions += [
        f"copy the voice to {target}",
        f"write the speaking script {paths.wrapper}",
        f"write the Speech Dispatcher module {paths.module_conf}",
    ]
    if dry_run:
        state = _read_state(paths)
        default_id = voice.id if make_default or not state.get("default") else state["default"]
        result.actions.append(f"use {default_id} as the module's default voice")
        if player is None:
            result.next_steps.append(
                "No audio player was found. Install pulseaudio-utils (paplay) or alsa-utils "
                "(aplay) before using the voice."
            )
        return result

    # Copy the voice (a fresh copy replaces an older one with the same id).
    staging = paths.voices / f".{voice.id}.installing"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copy2(voice.onnx, staging / f"{voice.id}.onnx")
    shutil.copy2(voice.config_path, staging / f"{voice.id}.onnx.json")
    (staging / "MODEL_CARD").write_text(voice.model_card_text, encoding="utf-8")
    info = dict(voice.info) or {
        "format": "vocalkeep-voice",
        "version": 1,
        "id": voice.id,
        "name": voice.name,
        "language": voice.language,
        "sampleRate": voice.sample_rate,
    }
    info["id"] = voice.id
    (staging / "voice.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    shutil.rmtree(target, ignore_errors=True)
    staging.replace(target)
    reporter.log(f"Copied the voice to {target}")

    state = _read_state(paths)
    if make_default or not state.get("default") or not (paths.voices / state["default"]).is_dir():
        state["default"] = voice.id
    state["python"] = python
    _write_state(paths, state)

    voices = _installed(paths)
    _write_files(paths, voices, state["default"], python)
    reporter.log(f"Wrote {paths.wrapper} and {paths.module_conf}")
    result.actions += update_speechd_conf(
        paths, want_module=True, make_default=make_default, language=voice.language
    )

    if player is None:
        result.next_steps.append(
            "No audio player was found. Install pulseaudio-utils (for paplay) or alsa-utils "
            "(for aplay), then run this install again."
        )
    warning = _check_runtime()
    if warning:
        result.next_steps.append(warning)
    result.next_steps += [
        "Restart Speech Dispatcher so it finds the voice: run  killall speech-dispatcher  "
        "(it starts again by itself when something speaks).",
        f'Test it:  spd-say -o {MODULE_NAME} "Hello, this is my voice."',
        "In Orca (the screen reader), choose the speech system 'Speech Dispatcher' and the "
        f"synthesizer '{MODULE_NAME}'.",
    ]
    if not make_default:
        result.next_steps.append(
            "To make it the voice everything uses, run the install again with --make-default."
        )
    return result


def uninstall_linux(voice_id: str, reporter: Reporter | None = None) -> LinuxResult:
    reporter = reporter or NullReporter()
    if not _SAFE_ID.match(voice_id):
        raise VocalkeepError(f"'{voice_id}' isn't a voice id.")
    paths = LinuxPaths.current()
    result = LinuxResult(voice_id)
    target = paths.voices / voice_id
    if not target.is_dir():
        installed = ", ".join(v.id for v in _installed(paths)) or "none"
        raise VocalkeepError(
            f"The voice {voice_id} isn't installed.", f"Installed Vocalkeep voices: {installed}."
        )
    shutil.rmtree(target)
    result.actions.append(f"removed {target}")
    state = _read_state(paths)
    voices = _installed(paths)
    if voices:
        if state.get("default") == voice_id or not state.get("default"):
            state["default"] = voices[0].id
        _write_state(paths, state)
        python = state.get("python") or sys.executable
        _write_files(paths, voices, state["default"], python)
        result.actions.append(f"updated {paths.wrapper} and {paths.module_conf}")
    else:
        for path in (paths.wrapper, paths.module_conf, paths.state):
            if path.exists():
                path.unlink()
                result.actions.append(f"removed {path}")
        result.actions += update_speechd_conf(
            paths, want_module=False, make_default=False, language=None
        )
        for folder in (paths.bin_dir, paths.voices, paths.data):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    result.next_steps.append(
        "Restart Speech Dispatcher so it forgets the voice: run  killall speech-dispatcher"
    )
    return result
