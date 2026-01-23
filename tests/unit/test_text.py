"""Tests for text encoding utilities."""

import pytest

from mudd.utils.text import decode_braille, encode_braille


class TestEncodeBraille:
    """Tests for Braille encoding of integers."""

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


class TestDecodeBraille:
    """Tests for Braille decoding back to integers."""

    def test_decodes_zero(self):
        """Blank braille pattern decodes to zero."""
        assert decode_braille("\u2800") == 0

    def test_decodes_small_number(self):
        """Single braille characters decode correctly."""
        assert decode_braille("\u2801") == 1
        assert decode_braille("\u28ff") == 255

    def test_decodes_multi_byte_number(self):
        """Multi-character strings decode correctly."""
        assert decode_braille("\u2801\u2800") == 256
        assert decode_braille("\u28ff\u28ff") == 65535

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
