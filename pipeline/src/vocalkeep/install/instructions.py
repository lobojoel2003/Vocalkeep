# SPDX-License-Identifier: GPL-3.0-or-later
"""Instructions for places Vocalkeep can't install to directly (phones, NVDA, macOS)."""

from __future__ import annotations

from vocalkeep.package import package_file_name
from vocalkeep.voice import Voice


def instructions(target: str, voice: Voice | None, voice_arg: str = "VOICE") -> list[str]:
    """Steps, one per line, for ``target`` (saywell, android, nvda or macos)."""
    vid = voice.id if voice else "<voice id>"
    name = voice.name if voice else "the"

    def pkg(fmt: str) -> str:
        return package_file_name(vid, fmt)

    def cmd(fmt: str) -> str:
        return f"vocalkeep package {voice_arg} --format {fmt} -o OUT_DIR"

    if target == "saywell":
        return [
            f"Saywell (the AAC app) can speak with {name}'s voice.",
            f"1. Make the package:  {cmd('saywell')}",
            f"   This makes {pkg('saywell')}.",
            "2. Copy that file to the phone or tablet (USB cable, cloud storage or email).",
            "3. In Saywell, open Settings, then 'Saywell voices' (under Voice).",
            f"4. Tap 'Install from a file' and choose {pkg('saywell')}.",
            "   Saywell says the voice is ready and lists it under 'On this device'.",
            "5. Select it, and set 'Voice to use' to 'Saywell voice (offline)' in Settings.",
        ]
    if target == "android":
        return [
            f"To make {name}'s voice the Android system voice (used by any app that talks):",
            f"1. Make the package:  {cmd('sherpatts')}",
            f"   This makes {pkg('sherpatts')} with HOW-TO-INSTALL.txt inside.",
            "2. Install SherpaTTS from F-Droid (org.woheller69.ttsengine).",
            "3. Unzip the package on the phone, open SherpaTTS > Manage Languages >",
            "   Install from SD Card, type the language code and a name, then pick model.onnx",
            "   and tokens.txt from the modelDir folder.",
            "4. In Android Settings > Text-to-speech output, choose SherpaTTS.",
            "Alternative: the app 'Piper for Android' imports the .onnx and .onnx.json from",
            f"   {pkg('piper')} ({cmd('piper')}).",
        ]
    if target == "nvda":
        return [
            f"To use {name}'s voice in the NVDA screen reader on Windows:",
            "1. Install the Sonata add-on for NVDA (https://github.com/mush42/sonata-nvda).",
            f"2. Make the package:  {cmd('nvda')}",
            f"   This makes {pkg('nvda')}.",
            "3. In NVDA, open the Sonata voice manager, choose 'Install from local file', and",
            f"   pick {pkg('nvda')}.",
            "4. In NVDA's speech settings choose the Sonata synthesizer and this voice.",
            "Note: Sonata had not been updated for NVDA 2026.1 (64-bit) when this was written,",
            "   so check that it supports your NVDA version. Otherwise use the Windows (SAPI)",
            "   voice: 'vocalkeep install VOICE --target windows' and NVDA's SAPI 5 synthesizer.",
        ]
    if target == "macos":
        return [
            f"To use {name}'s voice on a Mac:",
            "1. Install 'Piper Neural TTS' (https://github.com/piper-tts-apps/piper-app-apple).",
            f"2. Make the package:  {cmd('piper')}",
            f"   This makes {pkg('piper')}. Double-click it to unpack {vid}.onnx and",
            f"   {vid}.onnx.json.",
            "3. In Piper Neural TTS, import the voice and choose both files.",
            "4. Follow the app's steps to turn it on as a system voice (System Settings >",
            "   Accessibility > Spoken Content > System voice).",
        ]
    raise ValueError(target)
