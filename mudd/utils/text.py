"""Text encoding utilities."""

# Braille encoding for compact, non-distracting forum names
# U+2800 to U+28FF gives us 256 characters (base256)
BRAILLE_BASE = 0x2800


def encode_braille(num: int) -> str:
    """Encode an integer to a Braille pattern string (base256).

    Uses Unicode Braille Patterns block (U+2800-U+28FF) to encode
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
        return chr(BRAILLE_BASE)  # ⠀ (blank braille pattern)
    result = []
    while num:
        result.append(chr(BRAILLE_BASE + (num & 0xFF)))
        num >>= 8
    return "".join(reversed(result))


def decode_braille(encoded: str) -> int:
    """Decode a Braille pattern string back to an integer.

    Reverses encode_braille(). Each Braille character (U+2800-U+28FF)
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
