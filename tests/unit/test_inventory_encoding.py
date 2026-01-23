"""Tests for inventory forum name encoding."""

import pytest

from mudd.services.inventory import encode_braille, get_inventory_forum_name


class TestEncodeBraille:
    """Tests for Braille encoding of user IDs."""

    def test_encodes_zero(self):
        """Zero encodes to blank braille pattern U+2800."""
        result = encode_braille(0)
        assert result == "\u2800"
        assert len(result) == 1

    def test_encodes_small_number(self):
        """Small numbers encode to single characters."""
        # 1 should encode to U+2801
        result = encode_braille(1)
        assert result == "\u2801"
        assert len(result) == 1

        # 255 should encode to U+28FF (max single byte)
        result = encode_braille(255)
        assert result == "\u28ff"
        assert len(result) == 1

    def test_encodes_multi_byte_number(self):
        """Multi-byte numbers encode to multiple characters."""
        # 256 = 0x0100, should be 2 chars: U+2801 U+2800
        result = encode_braille(256)
        assert result == "\u2801\u2800"
        assert len(result) == 2

        # 65535 = 0xFFFF, should be 2 chars: U+28FF U+28FF
        result = encode_braille(65535)
        assert result == "\u28ff\u28ff"
        assert len(result) == 2

    def test_encodes_discord_user_id(self):
        """Real Discord user IDs (64-bit) encode to 8 chars max."""
        # Real Discord user ID
        user_id = 134129837962035201
        result = encode_braille(user_id)

        # Should be <= 8 characters (64 bits / 8 bits per char)
        assert len(result) <= 8

        # All characters should be in Braille Patterns block
        for char in result:
            assert 0x2800 <= ord(char) <= 0x28FF

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


class TestGetInventoryForumName:
    """Tests for forum name generation."""

    def test_includes_inventory_suffix(self):
        """Forum name ends with -inventory."""
        result = get_inventory_forum_name(12345)
        assert result.endswith("-inventory")

    def test_uses_braille_encoding(self):
        """Forum name uses Braille characters for user ID."""
        user_id = 134129837962035201
        result = get_inventory_forum_name(user_id)

        # Extract the encoded part (before -inventory)
        encoded_part = result[: -len("-inventory")]

        # All characters should be Braille
        for char in encoded_part:
            assert 0x2800 <= ord(char) <= 0x28FF

    def test_consistent_format(self):
        """Forum names follow {braille}-inventory format."""
        user_id = 134129837962035201
        result = get_inventory_forum_name(user_id)
        expected = f"{encode_braille(user_id)}-inventory"
        assert result == expected
