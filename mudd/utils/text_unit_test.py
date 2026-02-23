"""Tests for text encoding utilities."""

import pytest

from mudd.utils.text import (
    Rarity,
    decode_braille,
    encode_braille,
    indefinite_article,
    strip_rarity_emojis,
)


class TestEncodeBraille:
    """Tests for Braille encoding of integers."""

    def test_encodes_zero(self):
        """Zero encodes to U+2801 (not U+2800 which Discord strips)."""
        result = encode_braille(0)
        assert result == "\u2801"
        assert len(result) == 1

    def test_encodes_small_number(self):
        """Small numbers encode to single characters."""
        # 1 should encode to U+2802 (base + 1)
        result = encode_braille(1)
        assert result == "\u2802"
        assert len(result) == 1

        # 255 should encode to U+2900 (base + 255 = 0x2801 + 0xFF)
        result = encode_braille(255)
        assert result == "\u2900"
        assert len(result) == 1

    def test_encodes_multi_byte_number(self):
        """Multi-byte numbers encode to multiple characters."""
        # 256 = 0x0100, should be 2 chars: U+2802 U+2801
        result = encode_braille(256)
        assert result == "\u2802\u2801"
        assert len(result) == 2

        # 65535 = 0xFFFF, should be 2 chars: U+2900 U+2900
        result = encode_braille(65535)
        assert result == "\u2900\u2900"
        assert len(result) == 2

    def test_encodes_discord_user_id(self):
        """Real Discord user IDs (64-bit) encode to 8 chars max."""
        # Real Discord user ID
        user_id = 134129837962035201
        result = encode_braille(user_id)

        # Should be <= 8 characters (64 bits / 8 bits per char)
        assert len(result) <= 8

        # All characters should be in our Braille range (U+2801-U+2900)
        for char in result:
            assert 0x2801 <= ord(char) <= 0x2900

    def test_encoding_is_deterministic(self):
        """Same input always produces same output."""
        user_id = 134129837962035201
        result1 = encode_braille(user_id)
        result2 = encode_braille(user_id)
        assert result1 == result2

    def test_different_ids_produce_different_encodings(self):
        """Different user IDs produce different encodings."""
        result1 = encode_braille(134129837962035201)
        result2 = encode_braille(433125417583640576)
        assert result1 != result2

    def test_rejects_negative_numbers(self):
        """Negative numbers raise ValueError."""
        with pytest.raises(ValueError, match="negative"):
            encode_braille(-1)


class TestDecodeBraille:
    """Tests for Braille decoding back to integers."""

    def test_decodes_zero(self):
        """U+2801 (our base) decodes to zero."""
        assert decode_braille("\u2801") == 0

    def test_decodes_small_number(self):
        """Single braille characters decode correctly."""
        assert decode_braille("\u2802") == 1
        assert decode_braille("\u2900") == 255

    def test_decodes_multi_byte_number(self):
        """Multi-character strings decode correctly."""
        assert decode_braille("\u2802\u2801") == 256
        assert decode_braille("\u2900\u2900") == 65535

    def test_rejects_empty_string(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            decode_braille("")

    def test_rejects_non_braille_characters(self):
        """Non-Braille characters raise ValueError."""
        with pytest.raises(ValueError, match="Invalid Braille"):
            decode_braille("abc")


class TestBrailleRoundTrip:
    """Tests for encode/decode round-trip consistency."""

    @pytest.mark.parametrize("value", [0, 1, 255, 256, 65535, 16777215])
    def test_encode_decode_round_trip(self, value):
        """Encoding then decoding returns the original value."""
        assert decode_braille(encode_braille(value)) == value

    def test_round_trip_discord_user_ids(self):
        """Real Discord user IDs survive round-trip."""
        user_ids = [134129837962035201, 433125417583640576, 1]
        for user_id in user_ids:
            assert decode_braille(encode_braille(user_id)) == user_id

    def test_round_trip_max_64_bit(self):
        """Maximum 64-bit value survives round-trip."""
        max_64bit = (1 << 64) - 1
        assert decode_braille(encode_braille(max_64bit)) == max_64bit


class TestStripRarityEmojis:
    """Tests for stripping rarity emojis from text."""

    def test_strips_common_emoji(self):
        """Strips common (white circle) emoji."""
        result = strip_rarity_emojis("Test Item ⚪")
        assert result == "Test Item"

    def test_strips_uncommon_emoji(self):
        """Strips uncommon (green circle) emoji."""
        result = strip_rarity_emojis("Test Item 🟢")
        assert result == "Test Item"

    def test_strips_rare_emoji(self):
        """Strips rare (blue circle) emoji."""
        result = strip_rarity_emojis("Test Item 🔵")
        assert result == "Test Item"

    def test_strips_epic_emoji(self):
        """Strips epic (purple circle) emoji."""
        result = strip_rarity_emojis("Test Item 🟣")
        assert result == "Test Item"

    def test_strips_legendary_emoji(self):
        """Strips legendary (orange circle) emoji."""
        result = strip_rarity_emojis("Test Item 🟠")
        assert result == "Test Item"

    def test_strips_mythic_emoji(self):
        """Strips mythic (Japanese secret) emoji."""
        result = strip_rarity_emojis("Test Item ㊙️")
        assert result == "Test Item"

    def test_strips_quest_emoji(self):
        """Strips quest (blue diamond) emoji."""
        result = strip_rarity_emojis("Test Item 🔷")
        assert result == "Test Item"

    def test_preserves_text_without_emojis(self):
        """Text without rarity emojis is preserved."""
        result = strip_rarity_emojis("Wooden Table")
        assert result == "Wooden Table"

    def test_handles_empty_string(self):
        """Empty string returns empty string."""
        result = strip_rarity_emojis("")
        assert result == ""

    def test_strips_trailing_whitespace(self):
        """Trailing whitespace is stripped after emoji removal."""
        result = strip_rarity_emojis("Test Item 🟢  ")
        assert result == "Test Item"

    def test_strips_multiple_emojis(self):
        """Multiple rarity emojis are all removed."""
        result = strip_rarity_emojis("Test 🟢 Item 🔵")
        assert result == "Test  Item"

    @pytest.mark.parametrize("rarity,emoji", [(r, r.emoji) for r in Rarity])
    def test_strips_all_defined_emojis(self, rarity, emoji):
        """Every defined rarity emoji is stripped."""
        if emoji:  # Skip "none" which has empty emoji
            result = strip_rarity_emojis(f"Test Item {emoji}")
            assert result == "Test Item"


class TestIndefiniteArticle:
    """Tests for indefinite article helper."""

    def test_returns_a_for_consonant(self):
        """Words starting with consonants get 'a'."""
        assert indefinite_article("Ring Pop") == "a"
        assert indefinite_article("Balloon") == "a"

    def test_returns_an_for_vowel(self):
        """Words starting with vowels get 'an'."""
        assert indefinite_article("Apple") == "an"
        assert indefinite_article("Orange Soda") == "an"
        assert indefinite_article("ice cream") == "an"

    def test_handles_empty_string(self):
        """Empty string returns 'a' as default."""
        assert indefinite_article("") == "a"

    def test_strips_rarity_emoji_prefix(self):
        """Rarity emojis are ignored when determining article."""
        # Item with rare emoji prefix starting with vowel
        assert indefinite_article("🔵 Apple") == "an"
        # Item with common emoji prefix starting with consonant
        assert indefinite_article("⚪ Ring Pop") == "a"

    def test_case_insensitive(self):
        """Works regardless of case."""
        assert indefinite_article("apple") == "an"
        assert indefinite_article("APPLE") == "an"
        assert indefinite_article("Ring") == "a"
        assert indefinite_article("RING") == "a"
