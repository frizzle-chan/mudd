"""Scenario-driven integration tests for pay commands.

Tests the /pay command for transferring currency between players.
Covers autocomplete, validation, and transaction scenarios.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestPayCommandSuccess:
    """User successfully pays another user in the same room."""

    async def test_user_pays_another_user(self, test_client):
        """User pays another user in the same room."""
        sender = await test_client.create_user(user_id=500000001, room="foyer")
        recipient = await test_client.create_user(user_id=500000002, room="foyer")

        # Ensure both users have currency accounts
        await test_client.ensure_currency_account(sender.id, 1000)
        await test_client.ensure_currency_account(recipient.id, 1000)

        # Sender pays recipient 100 yen
        response = await test_client.pay(sender, str(recipient.id), 100)

        # Should confirm payment
        assert "You paid" in response

        # Verify balances
        sender_balance = await test_client.get_user_balance(sender.id)
        recipient_balance = await test_client.get_user_balance(recipient.id)
        assert sender_balance == 900
        assert recipient_balance == 1100


class TestPayCommandValidation:
    """User tries invalid payment scenarios."""

    async def test_insufficient_balance(self, test_client):
        """User tries to pay more than they have."""
        sender = await test_client.create_user(user_id=500000010, room="foyer")
        recipient = await test_client.create_user(user_id=500000011, room="foyer")

        # Sender has only 500 yen
        await test_client.ensure_currency_account(sender.id, 500)
        await test_client.ensure_currency_account(recipient.id, 1000)

        # Try to pay 1000 yen
        response = await test_client.pay(sender, str(recipient.id), 1000)

        # Should show error
        assert "don't have enough" in response

        # Balances should be unchanged
        sender_balance = await test_client.get_user_balance(sender.id)
        recipient_balance = await test_client.get_user_balance(recipient.id)
        assert sender_balance == 500
        assert recipient_balance == 1000

    async def test_payment_to_different_room(self, test_client):
        """User tries to pay someone in a different room."""
        sender = await test_client.create_user(user_id=500000020, room="foyer")
        recipient = await test_client.create_user(user_id=500000021, room="library")

        await test_client.ensure_currency_account(sender.id, 1000)
        await test_client.ensure_currency_account(recipient.id, 1000)

        # Try to pay someone in a different room
        response = await test_client.pay(sender, str(recipient.id), 100)

        # Should show error about location
        assert "not in the same room" in response

        # Balances should be unchanged
        sender_balance = await test_client.get_user_balance(sender.id)
        recipient_balance = await test_client.get_user_balance(recipient.id)
        assert sender_balance == 1000
        assert recipient_balance == 1000

    async def test_self_payment(self, test_client):
        """User tries to pay themselves."""
        user = await test_client.create_user(user_id=500000030, room="foyer")

        await test_client.ensure_currency_account(user.id, 1000)

        # Try to pay self
        response = await test_client.pay(user, str(user.id), 100)

        # Should show error
        assert "can't pay yourself" in response

        # Balance should be unchanged
        balance = await test_client.get_user_balance(user.id)
        assert balance == 1000

    async def test_invalid_amount_zero(self, test_client):
        """User tries to pay zero yen."""
        sender = await test_client.create_user(user_id=500000040, room="foyer")
        recipient = await test_client.create_user(user_id=500000041, room="foyer")

        await test_client.ensure_currency_account(sender.id, 1000)
        await test_client.ensure_currency_account(recipient.id, 1000)

        # Try to pay 0 yen
        response = await test_client.pay(sender, str(recipient.id), 0)

        # Should show error
        assert "must be positive" in response

        # Balances should be unchanged
        sender_balance = await test_client.get_user_balance(sender.id)
        recipient_balance = await test_client.get_user_balance(recipient.id)
        assert sender_balance == 1000
        assert recipient_balance == 1000

    async def test_invalid_amount_negative(self, test_client):
        """User tries to pay negative yen."""
        sender = await test_client.create_user(user_id=500000050, room="foyer")
        recipient = await test_client.create_user(user_id=500000051, room="foyer")

        await test_client.ensure_currency_account(sender.id, 1000)
        await test_client.ensure_currency_account(recipient.id, 1000)

        # Try to pay -100 yen
        response = await test_client.pay(sender, str(recipient.id), -100)

        # Should show error
        assert "must be positive" in response

        # Balances should be unchanged
        sender_balance = await test_client.get_user_balance(sender.id)
        recipient_balance = await test_client.get_user_balance(recipient.id)
        assert sender_balance == 1000
        assert recipient_balance == 1000

    async def test_payment_to_bot(self, test_client):
        """User tries to pay a bot."""
        sender = await test_client.create_user(user_id=500000060, room="foyer")
        bot_user = await test_client.create_user(user_id=500000061, room="foyer")

        await test_client.ensure_currency_account(sender.id, 1000)

        # Add a bot member to the guild
        await test_client.add_guild_member(bot_user.id, bot=True)

        # Try to pay the bot
        response = await test_client.pay(sender, str(bot_user.id), 100)

        # Should show error
        assert "bot" in response.lower()

        # Balance should be unchanged
        balance = await test_client.get_user_balance(sender.id)
        assert balance == 1000

    async def test_payment_without_account(self, test_client):
        """User tries to pay without having a currency account."""
        sender = await test_client.create_user(user_id=500000070, room="foyer")
        recipient = await test_client.create_user(user_id=500000071, room="foyer")

        # Recipient has account, sender doesn't
        await test_client.ensure_currency_account(recipient.id, 1000)

        # Try to pay
        response = await test_client.pay(sender, str(recipient.id), 100)

        # Should show error about sender not having account
        assert "don't have a currency account" in response

        # Recipient balance should be unchanged
        recipient_balance = await test_client.get_user_balance(recipient.id)
        assert recipient_balance == 1000

    async def test_payment_to_user_without_account(self, test_client):
        """User tries to pay someone who doesn't have a currency account."""
        sender = await test_client.create_user(user_id=500000080, room="foyer")
        recipient = await test_client.create_user(user_id=500000081, room="foyer")

        # Sender has account, recipient doesn't
        await test_client.ensure_currency_account(sender.id, 1000)

        # Try to pay
        response = await test_client.pay(sender, str(recipient.id), 100)

        # Should show error about recipient not having account
        assert "doesn't have a currency account" in response

        # Sender balance should be unchanged
        sender_balance = await test_client.get_user_balance(sender.id)
        assert sender_balance == 1000


class TestPayAutocomplete:
    """Autocomplete shows only valid recipients (users in same room)."""

    async def test_autocomplete_shows_same_room_users(self, test_client):
        """Autocomplete shows users in the same room."""
        user = await test_client.create_user(user_id=500000090, room="foyer")
        user2 = await test_client.create_user(user_id=500000091, room="foyer")
        user3 = await test_client.create_user(user_id=500000092, room="library")

        # Autocomplete should show user2 but not user3
        results = await test_client.recipient_autocomplete(user)
        values = [r.value for r in results]

        assert str(user2.id) in values
        assert str(user3.id) not in values

    async def test_autocomplete_excludes_self(self, test_client):
        """Autocomplete doesn't show the user themselves."""
        user = await test_client.create_user(user_id=500000100, room="foyer")
        user2 = await test_client.create_user(user_id=500000101, room="foyer")

        # Autocomplete should not show self
        results = await test_client.recipient_autocomplete(user)
        values = [r.value for r in results]

        assert str(user.id) not in values
        assert str(user2.id) in values

    async def test_autocomplete_filters_by_prefix(self, test_client):
        """Autocomplete filters by name using fuzzy matching."""
        user = await test_client.create_user(user_id=500000120, room="foyer")
        await test_client.create_user(
            user_id=500000121, room="foyer", display_name="Alice"
        )
        await test_client.create_user(
            user_id=500000122, room="foyer", display_name="Bob"
        )

        # Autocomplete with prefix "A" should show Alice
        results = await test_client.recipient_autocomplete(user, "A")
        names = [r.name for r in results]

        assert "Alice" in names
        assert "Bob" not in names

    async def test_autocomplete_empty_room(self, test_client):
        """Autocomplete shows placeholder when no valid recipients."""
        user = await test_client.create_user(user_id=500000130, room="hallway")

        # User is alone in the room
        results = await test_client.recipient_autocomplete(user)

        # Should have a placeholder
        assert len(results) == 1
        assert "nobody" in results[0].name.lower() or "invalid" in results[0].value
