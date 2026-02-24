"""Text encoding utilities."""

from __future__ import annotations

from enum import StrEnum


class Rarity(StrEnum):
    """Item rarity tiers with colocated display data."""

    NONE = "none"
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"
    QUEST = "quest"

    @property
    def emoji(self) -> str:
        """Emoji icon for this rarity tier."""
        match self:
            case Rarity.NONE:
                return ""
            case Rarity.COMMON:
                return "\u26aa"  # White circle
            case Rarity.UNCOMMON:
                return "\U0001f7e2"  # Green circle
            case Rarity.RARE:
                return "\U0001f535"  # Blue circle
            case Rarity.EPIC:
                return "\U0001f7e3"  # Purple circle
            case Rarity.LEGENDARY:
                return "\U0001f7e0"  # Orange circle
            case Rarity.MYTHIC:
                return "\u3299\ufe0f"  # Japanese "secret" symbol
            case Rarity.QUEST:
                return "\U0001f537"  # Blue diamond

    @property
    def spawn_weight(self) -> int:
        """Weight for spawning pool random selection."""
        match self:
            case Rarity.NONE:
                return 0  # Static world items never spawn
            case Rarity.COMMON:
                return 600
            case Rarity.UNCOMMON:
                return 250
            case Rarity.RARE:
                return 100
            case Rarity.EPIC:
                return 40
            case Rarity.LEGENDARY:
                return 9
            case Rarity.MYTHIC:
                return 1
            case Rarity.QUEST:
                return 600  # Same as common; use tags for dedicated pools

    @property
    def base_price(self) -> int:
        """Base price for shop trading. Non-tradeable rarities return 0."""
        match self:
            case Rarity.NONE:
                return 0
            case Rarity.COMMON:
                return 100
            case Rarity.UNCOMMON:
                return 1_000
            case Rarity.RARE:
                return 5_000
            case Rarity.EPIC:
                return 25_000
            case Rarity.LEGENDARY:
                return 100_000
            case Rarity.MYTHIC:
                return 500_000
            case Rarity.QUEST:
                return 0

    @property
    def sort_order(self) -> int:
        """Numeric sort order for rarity tiers (lowest rarity first)."""
        match self:
            case Rarity.NONE:
                return 0
            case Rarity.COMMON:
                return 1
            case Rarity.UNCOMMON:
                return 2
            case Rarity.RARE:
                return 3
            case Rarity.EPIC:
                return 4
            case Rarity.LEGENDARY:
                return 5
            case Rarity.MYTHIC:
                return 6
            case Rarity.QUEST:
                return 7


def strip_rarity_emojis(text: str) -> str:
    """Strip rarity emoji suffixes from text.

    Args:
        text: Text that may contain rarity emojis

    Returns:
        Text with all rarity emojis removed and stripped of trailing whitespace
    """
    for rarity in Rarity:
        if rarity.emoji:
            text = text.replace(rarity.emoji, "")
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
