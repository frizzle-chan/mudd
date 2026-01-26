"""Tests for inventory forum name generation."""

from mudd.services.inventory import get_inventory_forum_name


class TestGetInventoryForumName:
    """Tests for forum name generation."""

    def test_includes_inventory_suffix(self):
        """Forum name ends with -inventory."""
        result = get_inventory_forum_name("testuser")
        assert result.endswith("-inventory")

    def test_uses_username(self):
        """Forum name uses the Discord username."""
        username = "coolplayer123"
        result = get_inventory_forum_name(username)
        assert result == "coolplayer123-inventory"

    def test_consistent_format(self):
        """Forum names follow {username}-inventory format."""
        username = "some_user"
        result = get_inventory_forum_name(username)
        expected = f"{username}-inventory"
        assert result == expected
