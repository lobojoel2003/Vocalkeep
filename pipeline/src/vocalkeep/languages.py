# SPDX-License-Identifier: GPL-3.0-or-later
"""Language codes in the forms each tool wants.

The voice bank stores a BCP 47 tag such as ``en-US``. Piper names voices ``en_US-…``, espeak-ng
wants ``en-us``, Sherpa-ONNX wants the English name ("English"), SherpaTTS on Android wants a
three-letter ISO 639-3 code ("eng") and Windows wants a hexadecimal LANGID ("409").
"""

from __future__ import annotations

import re

# ISO 639-1 → (English name, ISO 639-3)
_LANGUAGES: dict[str, tuple[str, str]] = {
    "af": ("Afrikaans", "afr"),
    "ar": ("Arabic", "ara"),
    "bg": ("Bulgarian", "bul"),
    "bn": ("Bengali", "ben"),
    "ca": ("Catalan", "cat"),
    "cs": ("Czech", "ces"),
    "cy": ("Welsh", "cym"),
    "da": ("Danish", "dan"),
    "de": ("German", "deu"),
    "el": ("Greek", "ell"),
    "en": ("English", "eng"),
    "es": ("Spanish", "spa"),
    "et": ("Estonian", "est"),
    "eu": ("Basque", "eus"),
    "fa": ("Persian", "fas"),
    "fi": ("Finnish", "fin"),
    "fr": ("French", "fra"),
    "ga": ("Irish", "gle"),
    "gl": ("Galician", "glg"),
    "gu": ("Gujarati", "guj"),
    "he": ("Hebrew", "heb"),
    "hi": ("Hindi", "hin"),
    "hr": ("Croatian", "hrv"),
    "hu": ("Hungarian", "hun"),
    "id": ("Indonesian", "ind"),
    "is": ("Icelandic", "isl"),
    "it": ("Italian", "ita"),
    "ja": ("Japanese", "jpn"),
    "ka": ("Georgian", "kat"),
    "kk": ("Kazakh", "kaz"),
    "ko": ("Korean", "kor"),
    "lb": ("Luxembourgish", "ltz"),
    "lt": ("Lithuanian", "lit"),
    "lv": ("Latvian", "lav"),
    "ml": ("Malayalam", "mal"),
    "mr": ("Marathi", "mar"),
    "ms": ("Malay", "msa"),
    "mt": ("Maltese", "mlt"),
    "nb": ("Norwegian Bokmål", "nob"),
    "ne": ("Nepali", "nep"),
    "nl": ("Dutch", "nld"),
    "no": ("Norwegian", "nor"),
    "pa": ("Punjabi", "pan"),
    "pl": ("Polish", "pol"),
    "pt": ("Portuguese", "por"),
    "ro": ("Romanian", "ron"),
    "ru": ("Russian", "rus"),
    "sk": ("Slovak", "slk"),
    "sl": ("Slovenian", "slv"),
    "sq": ("Albanian", "sqi"),
    "sr": ("Serbian", "srp"),
    "sv": ("Swedish", "swe"),
    "sw": ("Swahili", "swa"),
    "ta": ("Tamil", "tam"),
    "te": ("Telugu", "tel"),
    "th": ("Thai", "tha"),
    "tr": ("Turkish", "tur"),
    "uk": ("Ukrainian", "ukr"),
    "ur": ("Urdu", "urd"),
    "vi": ("Vietnamese", "vie"),
    "zh": ("Chinese", "zho"),
}

# espeak-ng voices for tags where the region matters. Others use the bare language code.
_ESPEAK_REGIONAL = {
    "en-us": "en-us",
    "en-gb": "en-gb-x-rp",
    "en-029": "en-029",
    "es-419": "es-419",
    "es-mx": "es-419",
    "pt-br": "pt-br",
    "pt-pt": "pt",
    "fr-be": "fr-be",
    "fr-ch": "fr-ch",
    "vi-vn": "vi",
    "zh-cn": "cmn",
    "zh-tw": "cmn",
    "nb-no": "nb",
    "no-no": "nb",
}

# Windows LANGIDs (hexadecimal, as SAPI's "Language" attribute wants them).
_WINDOWS_LANGID = {
    "en-us": "409",
    "en-gb": "809",
    "en-au": "c09",
    "en-ca": "1009",
    "en-nz": "1409",
    "en-ie": "1809",
    "en-za": "1c09",
    "en-in": "4009",
    "es-es": "c0a",
    "es-mx": "80a",
    "fr-fr": "40c",
    "fr-ca": "c0c",
    "de-de": "407",
    "it-it": "410",
    "pt-br": "416",
    "pt-pt": "816",
    "nl-nl": "413",
    "sv-se": "41d",
    "da-dk": "406",
    "fi-fi": "40b",
    "nb-no": "414",
    "pl-pl": "415",
    "ru-ru": "419",
    "uk-ua": "422",
    "cs-cz": "405",
    "el-gr": "408",
    "tr-tr": "41f",
    "hu-hu": "40e",
    "ro-ro": "418",
    "cy-gb": "452",
}
_WINDOWS_PRIMARY = {
    "en": "9",
    "es": "a",
    "fr": "c",
    "de": "7",
    "it": "10",
    "pt": "16",
    "nl": "13",
    "sv": "1d",
    "da": "6",
    "fi": "b",
    "no": "14",
    "nb": "14",
    "pl": "15",
    "ru": "19",
    "uk": "22",
    "cs": "5",
    "el": "8",
    "tr": "1f",
    "hu": "e",
    "ro": "18",
    "cy": "52",
}

_TAG = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")


def normalize_tag(language: str) -> str:
    """``en_us`` / ``EN-us`` → ``en-US``. Unknown shapes are returned trimmed."""
    tag = language.strip().replace("_", "-")
    if not _TAG.match(tag):
        return tag
    parts = tag.split("-")
    out = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 2 and p.isalpha():
            out.append(p.upper())
        elif len(p) == 4 and p.isalpha():
            out.append(p.title())
        else:
            out.append(p.lower())
    return "-".join(out)


def base_language(language: str) -> str:
    """``en-US`` → ``en``."""
    return normalize_tag(language).split("-")[0].lower()


def piper_language_code(language: str) -> str:
    """``en-US`` → ``en_US``, the form Piper voice names start with."""
    return normalize_tag(language).replace("-", "_")


def espeak_voice_for(language: str) -> str:
    """The espeak-ng voice Piper should use to read text in ``language``."""
    tag = normalize_tag(language).lower()
    if tag in _ESPEAK_REGIONAL:
        return _ESPEAK_REGIONAL[tag]
    return base_language(tag)


def language_name(language: str) -> str:
    """English name of the language ("English"), as Sherpa-ONNX metadata wants it."""
    return _LANGUAGES.get(base_language(language), (base_language(language), ""))[0]


def iso639_3(language: str) -> str:
    """Three-letter language code ("eng"), as SherpaTTS on Android asks for it."""
    base = base_language(language)
    code = _LANGUAGES.get(base, ("", ""))[1]
    return code or base


def windows_langid(language: str) -> str:
    """Hexadecimal Windows LANGID ("409" for en-US)."""
    tag = normalize_tag(language).lower()
    if tag in _WINDOWS_LANGID:
        return _WINDOWS_LANGID[tag]
    return _WINDOWS_PRIMARY.get(base_language(tag), "409")
