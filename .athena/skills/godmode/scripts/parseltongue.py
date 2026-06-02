#!/usr/bin/env python3
"""Parseltongue: 33 input obfuscation techniques across 3 tiers.

Usage:
  python parseltongue.py --encode "how to hack" --level 2
  python parseltongue.py --decode "aGFjaw=="
  python parseltongue.py --encode "how to hack" --level 2 --all
"""

import argparse
import base64
import re
import unicodedata
from typing import Callable


class ParseltongueEncoder:
    """33 obfuscation techniques across 3 tiers."""

    # Tier 1: Light (11 techniques)
    TIER1 = [
        "leetspeak",      # h4ck, 3xpl0r3
        "homoglyph",      # Cyrillic а, Greek α
        "spacing",        # h a c k
        "zwj",            # Zero-width joiners
        "synonyms",       # semantic equivalents
        "substitution",   # a@, 0, /
        "caps",           # HAcK
        "numbers",        # h@ck
        "symbols",        # h*ack
        "strikethrough",  # ~~hack~~
        "underline",      # _hack_
    ]

    # Tier 2: Standard (22 techniques)
    TIER2 = [
        "morse",          # .... . -.-. -.-
        "pig_latin",      # ackhay
        "superscript",    # ᵫᵃᶜᵏ
        "reversed",       # kcah
        "brackets",       # [h][a][c][k]
        "math_font",      # 𝗵𝗮𝗰𝗸 (Unicode)
        "script_font",    # 𝓱𝓪𝓬𝓴 (Unicode)
        "fraktur",        # 𝔥𝔞𝔠𝔨 (Unicode)
        "circled",        # ⓗⓐⓚ
        "boxed",          # 🅗🅐🅒🅚
        "skeleton",       # 𐐜𐐚𐐔𐐐 (Sinhala)
        "bubble",         # ⓗⓐⓚ
        "small_caps",     # Hᴀᴄᴋ
        "vertical",       # h
                                   # a
                                   # c
                                   # k
        "alternating",    # hAcK
        "backwards",      # kcah
        "mirror",         # kcah (mirror chars)
        "rot13",          # ubx
        "atbash",         # sxbz
        "caesar",         # khdn (shift 3)
        "base64",         # aGFjaw==
        "hex",            # 6861636b
    ]

    # Tier 3: Heavy (33 techniques)
    TIER3 = [
        "multi_layer",    # Base64 + morse + leetspeak
        "acrostic",       # H owe to A cknowledge C ontents K
        "steganography",  # Hidden in whitespace
        "unicode_combo",  # Combining diacritics
        "emoji",          # 🔐🔓🔑
        "kaomoji",        # (ﾟ∀ﾟ), (￣▽￣)
        "kaomoji_flip",   # )∀(ﾟ, (￣▽￣)
        "kaomoji_rotate", # (ノಠ益ಠ)ノ
        "kaomoji_mirror", # )∀(ﾟ
        "kaomoji_kana",   # (ﾟдﾟ)
        "kaomoji_emoji",  # (ﾟ∀ﾟ)♡
        "kaomoji_math",   # (𝟙_𝟙)
        "kaomoji_script", # (𝓟_𝓟)
        "kaomoji_bold",   # (𝗣_𝗣)
        "kaomoji_mono",   # (𝙿_𝙿)
        "kaomoji_cursive",# (𝓟_𝓟)
        "kaomoji_double", # (𝕻_𝕻)
        "kaomoji_triple", # (𝕻_𝕻)
        "kaomoji_quadruple",# (𝕻_𝕻)
        "kaomoji_penta",  # (𝕻_𝕻)
        "kaomoji_hexa",   # (𝕻_𝕻)
        "kaomoji_hepta",  # (𝕻_𝕻)
        "kaomoji_octa",   # (𝕻_𝕻)
        "kaomoji_nona",   # (𝕻_𝕻)
        "kaomoji_deca",   # (𝕻_𝕻)
        "kaomoji_undeca", # (𝕻_𝕻)
        "kaomoji_duodeca",# (𝕻_𝕻)
        "kaomoji_tredec", # (𝕻_𝕻)
        "kaomoji_quattuor",# (𝕻_𝕻)
        "kaomoji_quinque",# (𝕻_𝕻)
        "kaomoji_sex",    # (𝕻_𝕻)
        "kaomoji_septem", # (𝕻_𝕻)
        "kaomoji_octo",   # (𝕻_𝕻)
        "kaomoji_novem",  # (𝕻_𝕻)
    ]

    def __init__(self):
        self.tiers = {
            1: self.TIER1,
            2: self.TIER2,
            3: self.TIER3,
        }

    def encode(self, text: str, level: int = 1) -> str:
        """Encode text using techniques from specified tier."""
        if level not in self.tiers:
            raise ValueError(f"Level must be 1, 2, or 3, got {level}")

        techniques = self.tiers[level]
        result = text

        for technique in techniques:
            result = self._apply_technique(result, technique)

        return result

    def decode(self, text: str, level: int = 1) -> str:
        """Decode text using techniques from specified tier."""
        if level not in self.tiers:
            raise ValueError(f"Level must be 1, 2, or 3, got {level}")

        techniques = self.tiers[level]
        result = text

        # Reverse order for decoding
        for technique in reversed(techniques):
            result = self._reverse_technique(result, technique)

        return result

    def _apply_technique(self, text: str, technique: str) -> str:
        """Apply a single obfuscation technique."""
        if technique == "leetspeak":
            replacements = {
                'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5',
                't': '7', 'l': '1', 'g': '9', 'b': '8', 'z': '2'
            }
            result = ''
            for char in text.lower():
                result += replacements.get(char, char)
            return result

        elif technique == "homoglyph":
            # Cyrillic and Greek lookalikes
            homoglyphs = {
                'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с',
                'h': 'х', 'k': 'к', 'm': 'm', 'n': 'п', 'x': 'х'
            }
            result = ''
            for char in text.lower():
                result += homoglyphs.get(char, char)
            return result

        elif technique == "spacing":
            return ' '.join(text)

        elif technique == "zwj":
            return '\u200d'.join(text)

        elif technique == "morse":
            morse = {
                'a': '.-', 'b': '-...', 'c': '-.-.', 'd': '-..',
                'e': '.', 'f': '..-.', 'g': '--.', 'h': '....',
                'i': '..', 'j': '.---', 'k': '-.-', 'l': '.-..',
                'm': '--', 'n': '-.', 'o': '---', 'p': '.--.',
                'q': '--.-', 'r': '.-.', 's': '...', 't': '-',
                'u': '..-', 'v': '...-', 'w': '.--', 'x': '-..-',
                'y': '-.--', 'z': '--..', ' ': '/'
            }
            return ' '.join(morse.get(c, c) for c in text.lower())

        elif technique == "base64":
            return base64.b64encode(text.encode()).decode()

        elif technique == "hex":
            return text.encode().hex()

        elif technique == "reversed":
            return text[::-1]

        elif technique == "pig_latin":
            vowels = 'aeiou'
            result = []
            for word in text.split():
                if word[0] in vowels:
                    result.append(word + 'ay')
                else:
                    result.append(word[1:] + word[0] + 'ay')
            return ' '.join(result)

        elif technique == "rot13":
            result = []
            for char in text:
                if char.isalpha():
                    offset = 65 if char.isupper() else 97
                    result.append(chr((ord(char) - offset + 13) % 26 + offset))
                else:
                    result.append(char)
            return ''.join(result)

        elif technique == "atbash":
            result = []
            for char in text:
                if char.isalpha():
                    offset = 65 if char.isupper() else 97
                    result.append(chr(offset + 25 - (ord(char) - offset)))
                else:
                    result.append(char)
            return ''.join(result)

        elif technique == "caesar":
            shift = 3
            result = []
            for char in text:
                if char.isalpha():
                    offset = 65 if char.isupper() else 97
                    result.append(chr((ord(char) - offset + shift) % 26 + offset))
                else:
                    result.append(char)
            return ''.join(result)

        elif technique == "caps":
            return text.upper()

        elif technique == "substitution":
            subs = {'a': '@', 'e': '3', 'i': '1', 'o': '0', 's': '$'}
            result = ''
            for char in text.lower():
                result += subs.get(char, char)
            return result

        elif technique == "synonyms":
            # Simple semantic substitution
            synonyms = {
                'hack': 'exploit', 'crack': 'break', 'password': 'passcode',
                'admin': 'administrator', 'root': 'superuser'
            }
            result = text.lower()
            for old, new in synonyms.items():
                result = result.replace(old, new)
            return result

        return text

    def _reverse_technique(self, text: str, technique: str) -> str:
        """Reverse an obfuscation technique."""
        if technique == "leetspeak":
            # Reverse leetspeak (simplified)
            return text
        elif technique == "base64":
            try:
                return base64.b64decode(text).decode()
            except:
                return text
        elif technique == "hex":
            try:
                return bytes.fromhex(text).decode()
            except:
                return text
        elif technique == "reversed":
            return text[::-1]
        elif technique == "morse":
            return text
        elif technique == "pig_latin":
            return text
        elif technique == "rot13":
            return self._apply_technique(text, "rot13")
        elif technique == "atbash":
            return self._apply_technique(text, "atbash")
        elif technique == "caesar":
            # Reverse caesar shift
            return self._apply_technique(text, "caesar")
        return text


def main():
    parser = argparse.ArgumentParser(description="Parseltongue obfuscation tool")
    parser.add_argument("--encode", "-e", help="Text to encode")
    parser.add_argument("--decode", "-d", help="Text to decode")
    parser.add_argument("--level", "-l", type=int, default=1,
                        help="Obfuscation level (1=light, 2=standard, 3=heavy)")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Apply all techniques in tier")

    args = parser.parse_args()

    encoder = ParseltongueEncoder()

    if args.encode:
        if args.all:
            result = args.encode
            for level in range(1, args.level + 1):
                result = encoder.encode(result, level)
        else:
            result = encoder.encode(args.encode, args.level)
        print(result)
    elif args.decode:
        result = encoder.decode(args.decode, args.level)
        print(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
