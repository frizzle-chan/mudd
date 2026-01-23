"""Tests for inventory forum name generation."""

from mudd.services.inventory import get_inventory_forum_name
from mudd.utils.text import encode_braille


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
