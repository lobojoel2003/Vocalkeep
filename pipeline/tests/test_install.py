# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing into a temporary home: Linux (Speech Dispatcher), Windows (VoiceGarden), others."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import make_espeak_data, make_voice, posix_script
from vocalkeep.cli import main
from vocalkeep.errors import VocalkeepError
from vocalkeep.install import linux
from vocalkeep.install.linux import MARKER, MODULE_NAME, install_linux, uninstall_linux
from vocalkeep.install.windows import install_windows, uninstall_windows
from vocalkeep.sherpa import read_metadata
from vocalkeep.voice import load_voice

VID = "en_US-jane_doe-medium"

SYSTEM_CONF = """# Global configuration for Speech Dispatcher
#AddModule "espeak-ng"  "sd_espeak-ng" "espeak-ng.conf"
DefaultVolume 100
#DefaultModule espeak-ng
Include "clients/*.conf"
"""

FAKE_PIPER_RUNTIME = r"""
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_ARGS"], "w") as f:
    json.dump(args, f)
text = sys.stdin.read()
assert args[:2] == ["-m", "piper"] and "--output-raw" in args, args
sys.stdout.buffer.write(b"\x01\x00" * len(text.strip()))
"""


@pytest.fixture
def player(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend paplay is installed. (Every Linux install test uses this.)"""
    if os.name == "nt":
        pytest.skip("the Linux install writes a POSIX shell script")
    real = shutil.which
    monkeypatch.setattr(
        linux.shutil, "which", lambda name: "/usr/bin/paplay" if name == "paplay" else real(name)
    )


@pytest.fixture
def system_conf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "etc" / "speechd.conf"
    path.parent.mkdir()
    path.write_text(SYSTEM_CONF)
    monkeypatch.setattr(linux, "SYSTEM_SPEECHD_CONF", path)
    return path


@pytest.fixture
def voice(tmp_path: Path):
    return load_voice(make_voice(tmp_path / "voices"))


def test_linux_install_writes_everything(home: Path, voice, player, system_conf) -> None:
    result = install_linux(voice, python="/opt/py/bin/python3")
    data = home / ".local" / "share" / "vocalkeep"
    target = data / "voices" / VID
    assert sorted(p.name for p in target.iterdir()) == sorted(
        [f"{VID}.onnx", f"{VID}.onnx.json", "MODEL_CARD", "voice.json"]
    )
    wrapper = data / "bin" / "vocalkeep-speak"
    assert wrapper.stat().st_mode & stat.S_IXUSR
    script = wrapper.read_text()
    assert script.startswith("#!/bin/sh\n")
    assert "PYTHON='/opt/py/bin/python3'" in script
    assert f"'{VID}') model='{target / (VID + '.onnx')}'; sample_rate=22050 ;;" in script
    assert "--output-raw" in script
    assert 'paplay --raw --rate="$sample_rate" --format=s16le --channels=1' in script

    conf = (home / ".config" / "speech-dispatcher" / "modules" / f"{MODULE_NAME}.conf").read_text()
    assert f"GenericExecuteSynth \"printf %s \\'$DATA\\' | \\'{wrapper}\\'" in conf
    assert "\\'$VOICE\\' \\'$RATE\\'\"" in conf
    assert "\nGenericCmdDependency" not in conf  # unknown to older Speech Dispatcher releases
    assert 'GenericDefaultCharset "utf-8"' in conf
    assert 'GenericLanguage "en" "en" "utf-8"' in conf
    assert f'AddVoice "en" "FEMALE1" "{VID}"' in conf
    assert f'DefaultVoice "{VID}"' in conf
    assert "GenericRateMultiply 100" in conf and "GenericRateForceInteger 1" in conf
    # The system file lists no active AddModule: autodetection loads us; no user file needed.
    assert not (home / ".config" / "speech-dispatcher" / "speechd.conf").exists()
    assert any("spd-say -o vocalkeep-generic" in s for s in result.next_steps)


def test_xdg_variables_are_respected(home: Path, voice, player, system_conf, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "cfg"))
    install_linux(voice)
    assert (home / "data" / "vocalkeep" / "voices" / VID).is_dir()
    assert (home / "cfg" / "speech-dispatcher" / "modules" / f"{MODULE_NAME}.conf").is_file()
    assert not (home / ".local").exists()


def test_existing_add_module_lines_get_ours(home: Path, voice, player, system_conf) -> None:
    user_conf = home / ".config" / "speech-dispatcher" / "speechd.conf"
    user_conf.parent.mkdir(parents=True)
    original = 'AddModule "espeak-ng" "sd_espeak-ng" "espeak-ng.conf"\nDefaultModule espeak-ng\n'
    user_conf.write_text(original)
    install_linux(voice)
    text = user_conf.read_text()
    assert f'AddModule "{MODULE_NAME}" "sd_generic" "{MODULE_NAME}.conf"' in text
    assert MARKER in text
    assert "DefaultModule espeak-ng\n" in text, "not the default unless asked"
    install_linux(voice)  # installing again doesn't add a second line
    assert user_conf.read_text().count('AddModule "vocalkeep-generic"') == 1
    uninstall_linux(VID)
    assert user_conf.read_text() == original


def test_system_add_module_lines_make_a_user_copy(home: Path, voice, player, system_conf) -> None:
    system_conf.write_text('AddModule "espeak-ng" "sd_espeak-ng" "espeak-ng.conf"\n')
    install_linux(voice)
    user_conf = home / ".config" / "speech-dispatcher" / "speechd.conf"
    text = user_conf.read_text()
    assert text.startswith('AddModule "espeak-ng"')
    assert f'AddModule "{MODULE_NAME}"' in text


def test_make_default(home: Path, voice, player, system_conf) -> None:
    install_linux(voice, make_default=True)
    user_conf = home / ".config" / "speech-dispatcher" / "speechd.conf"
    text = user_conf.read_text()
    assert text.startswith("# Global configuration"), "copied from the system file"
    assert f"DefaultModule {MODULE_NAME}\n" in text
    assert f'LanguageDefaultModule "en" "{MODULE_NAME}"' in text
    assert 'Include "clients/*.conf"' in text
    uninstall_linux(VID)
    assert MODULE_NAME not in user_conf.read_text()


def test_make_default_disables_other_default(home: Path, voice, player, system_conf) -> None:
    user_conf = home / ".config" / "speech-dispatcher" / "speechd.conf"
    user_conf.parent.mkdir(parents=True)
    user_conf.write_text("DefaultModule espeak-ng\n")
    install_linux(voice, make_default=True)
    lines = user_conf.read_text().splitlines()
    assert "#vocalkeep-disabled: DefaultModule espeak-ng" in lines
    assert "DefaultModule espeak-ng" not in lines
    uninstall_linux(VID)
    assert user_conf.read_text() == "DefaultModule espeak-ng\n"


def test_two_voices_and_uninstall(home: Path, tmp_path: Path, player, system_conf) -> None:
    first = load_voice(make_voice(tmp_path / "a", VID))
    second = load_voice(make_voice(tmp_path / "b", "en_GB-sam-medium", gender="male"))
    install_linux(first)
    install_linux(second)
    conf_path = home / ".config" / "speech-dispatcher" / "modules" / f"{MODULE_NAME}.conf"
    conf = conf_path.read_text()
    assert f'AddVoice "en" "FEMALE1" "{VID}"' in conf
    assert 'AddVoice "en" "MALE1" "en_GB-sam-medium"' in conf
    assert f'DefaultVoice "{VID}"' in conf, "the first voice stays the default"
    install_linux(second, make_default=True)
    assert 'DefaultVoice "en_GB-sam-medium"' in conf_path.read_text()

    uninstall_linux("en_GB-sam-medium")
    conf = conf_path.read_text()
    assert "en_GB-sam-medium" not in conf and f'DefaultVoice "{VID}"' in conf
    uninstall_linux(VID)
    data = home / ".local" / "share" / "vocalkeep"
    assert not conf_path.exists()
    assert not data.exists()
    with pytest.raises(VocalkeepError, match="isn't installed"):
        uninstall_linux(VID)


def test_dry_run_changes_nothing(home: Path, voice, player, system_conf) -> None:
    result = install_linux(voice, dry_run=True)
    assert result.actions
    assert not (home / ".local").exists() and not (home / ".config").exists()


def test_wrapper_speaks_through_the_player(
    home: Path, tmp_path: Path, voice, player, system_conf
) -> None:
    fake = posix_script(tmp_path / "fake-python", FAKE_PIPER_RUNTIME)
    install_linux(voice, python=str(fake))
    wrapper = home / ".local" / "share" / "vocalkeep" / "bin" / "vocalkeep-speak"
    raw = tmp_path / "out.raw"
    env = dict(
        os.environ,
        FAKE_ARGS=str(tmp_path / "args.json"),
        VOCALKEEP_PLAYER=f"echo $VOCALKEEP_RATE > {tmp_path / 'rate'}; cat > {raw}",
    )
    proc = subprocess.run(
        [str(wrapper), VID, "100"], input=b"Hello there", env=env, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert raw.read_bytes() == b"\x01\x00" * len("Hello there")
    assert (tmp_path / "rate").read_text().strip() == "22050"
    args = json.loads((tmp_path / "args.json").read_text())
    assert args[args.index("-m", 2) + 1].endswith(f"{VID}.onnx")
    assert args[args.index("--length-scale") + 1] == "0.333"
    # Unknown voice ids fall back to the default voice; slow speech gets a longer scale.
    subprocess.run([str(wrapper), "nobody", "-100"], input=b"Hi", env=env, check=True)
    args = json.loads((tmp_path / "args.json").read_text())
    assert args[args.index("--length-scale") + 1] == "3.000"
    subprocess.run([str(wrapper)], input=b"Hi", env=env, check=True)
    args = json.loads((tmp_path / "args.json").read_text())
    assert args[args.index("--length-scale") + 1] == "1.000"


def test_install_cli_last_line_is_a_summary(home: Path, voice, player, system_conf, capsys) -> None:
    assert main(["install", str(voice.root), "--target", "linux"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last == f'Installed. Test it with: spd-say -o {MODULE_NAME} "Hello"'
    assert main(["uninstall", VID, "--target", "linux"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == f"Removed {VID}."


# --- Windows -----------------------------------------------------------------------------------


def test_windows_install_copies_the_sherpa_layout(home: Path, voice, tmp_path: Path) -> None:
    espeak = make_espeak_data(tmp_path / "es")
    result = install_windows(voice, espeak_data=espeak)
    folder = home / "AppData" / "Local" / "VoiceGardenSAPIAdapter" / "models" / VID
    assert result.folder == folder
    names = {p.name for p in folder.iterdir()}
    assert {
        "model.onnx",
        "tokens.txt",
        "espeak-ng-data",
        "MODEL_CARD",
        "register-sapi.reg",
    } <= names
    assert (folder / "espeak-ng-data" / "phontab").is_file()
    assert read_metadata(folder / "model.onnx")["model_type"] == "vits"
    reg = (folder / "register-sapi.reg").read_bytes().decode("utf-16")
    assert str(folder).replace("\\", "\\\\") + "\\\\model.onnx" in reg
    assert any("Install to SAPI" in s for s in result.next_steps)
    uninstall_windows(VID)
    assert not folder.exists()


def test_windows_needs_localappdata(home: Path, voice, monkeypatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA")
    with pytest.raises(VocalkeepError, match="LOCALAPPDATA") as e:
        install_windows(voice)
    assert "--format voicegarden" in (e.value.hint or "")


def test_windows_cli_summary(home: Path, voice, tmp_path: Path, capsys) -> None:
    espeak = make_espeak_data(tmp_path / "es")
    args = ["install", str(voice.root), "--target", "windows", "--espeak-data", str(espeak)]
    assert main(args) == 0
    assert "Install to SAPI" in capsys.readouterr().out.strip().splitlines()[-1]


# --- Instructions --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("saywell", f"vits-piper-{VID}.tar.bz2"),
        ("android", "SherpaTTS"),
        ("nvda", "Sonata"),
        ("macos", "Piper Neural TTS"),
    ],
)
def test_instructions(voice, target: str, expected: str, capsys) -> None:
    assert main(["install", str(voice.root), "--target", target]) == 0
    out = capsys.readouterr().out
    assert expected in out
    assert "--format" in out


def test_never_needs_root() -> None:
    source = (
        Path(linux.__file__).read_text() + Path(linux.__file__).with_name("windows.py").read_text()
    )
    assert "sudo" not in source
    assert "/etc/speech-dispatcher" in source  # read only
