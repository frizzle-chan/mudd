"""Text encoding utilities."""

from typing import Literal

# Rarity type literal (must match entity.py's Rarity type)
Rarity = Literal[
    "none", "common", "uncommon", "rare", "epic", "legendary", "mythic", "quest"
]

# Rarity emoji for display names
RARITY_EMOJI: dict[Rarity, str] = {
    "none": "",  # No emoji for static world items
    "common": "\u26aa",  # White circle
    "uncommon": "\U0001f7e2",  # Green circle
    "rare": "\U0001f535",  # Blue circle
    "epic": "\U0001f7e3",  # Purple circle
    "legendary": "\U0001f7e0",  # Orange circle
    "mythic": "\u3299\ufe0f",  # Japanese "secret" symbol
    "quest": "\U0001f537",  # Blue diamond
}


def strip_rarity_emojis(text: str) -> str:
    """Strip rarity emoji suffixes from text.

    Args:
        text: Text that may contain rarity emojis

    Returns:
        Text with all rarity emojis removed and stripped of trailing whitespace
    """
    for emoji in RARITY_EMOJI.values():
        if emoji:
            text = text.replace(emoji, "")
    return text.strip()


def indefinite_article(word: str) -> str:
    """Return 'a' or 'an' based on the word's starting sound.

    Uses simple vowel detection. Works for most common nouns.

    Args:
        word: The word to determine the article for

    Returns:
        'a' or 'an' depending on the starting letter
    """
    if not word:
        return "a"
    # Strip rarity emojis that might prefix the display name
    clean = strip_rarity_emojis(word).lstrip()
    if not clean:
        return "a"
    return "an" if clean[0].lower() in "aeiou" else "a"


# Braille encoding for compact, non-distracting forum names
# U+2801 to U+2900 gives us 256 characters (base256)
# NOTE: We start at U+2801 (not U+2800) because U+2800 is the blank Braille
# pattern which Discord strips from channel names like whitespace.
BRAILLE_BASE = 0x2801


def encode_braille(num: int) -> str:
    """Encode an integer to a Braille pattern string (base256).

    Uses Unicode Braille Patterns block (U+2801-U+2900) to encode
    integers compactly. Each character represents one byte (0-255).

    Discord user IDs (64-bit) encode to 8 characters max.
    The result is visually unobtrusive (appears as dot patterns).

    Args:
        num: Non-negative integer to encode

    Raises:
        ValueError: If num is negative
    """
    if num < 0:
        raise ValueError("Cannot encode negative numbers")
    if num == 0:
        return chr(BRAILLE_BASE)  # ⠁ (single dot braille pattern)
    result = []
    while num:
        result.append(chr(BRAILLE_BASE + (num & 0xFF)))
        num >>= 8
    return "".join(reversed(result))


def decode_braille(encoded: str) -> int:
    """Decode a Braille pattern string back to an integer.

    Reverses encode_braille(). Each Braille character (U+2801-U+2900)
    represents one byte (0-255).

    Args:
        encoded: Braille pattern string from encode_braille()

    Raises:
        ValueError: If string is empty or contains non-Braille characters
    """
    if not encoded:
        raise ValueError("Cannot decode empty string")
    result = 0
    for char in encoded:
        codepoint = ord(char)
        if not (BRAILLE_BASE <= codepoint <= BRAILLE_BASE + 0xFF):
            raise ValueError(f"Invalid Braille character: {char!r}")
        result = (result << 8) | (codepoint - BRAILLE_BASE)
    return result
