"""Core type definitions for MUDD."""

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mudd.services.currency import CurrencyService


class UserContext:
    """User context for templates with optional lazy balance fetching.

    Provides user-specific context for template rendering. Templates can
    access user.name, user.mention, and optionally user.balance() for
    lazy wallet balance fetching.

    Usage in cogs (with balance support):
        user = UserContext(
            name=interaction.user.display_name,
            mention=interaction.user.mention,
            user_id=interaction.user.id,
            currency_service=self._currency,
        )

    Usage in tests (minimal):
        user = UserContext(name="Frizzle", mention="<@12345>")
    """

    def __init__(
        self,
        name: str,
        mention: str,
        user_id: int | None = None,
        currency_service: "CurrencyService | None" = None,
    ) -> None:
        self.name = name
        self.mention = mention
        self._user_id = user_id
        self._currency = currency_service

    async def balance(self) -> int:
        """Fetch user's wallet balance.

        Returns:
            Balance as integer. Use {{ user.balance() | money }} in templates
            for formatted output like "¥1,000".
        """
        if self._currency is None or self._user_id is None:
            return 0
        balance = await self._currency.get_balance(self._user_id)
        return balance if balance else 0


class VerbAction(str, Enum):
    """Action types for verb-to-handler mapping.

    Values match the PostgreSQL verb_action enum and entity handler column names.
    """

    ON_LOOK = "on_look"
    ON_TOUCH = "on_touch"
    ON_ATTACK = "on_attack"
    ON_USE = "on_use"
    ON_TAKE = "on_take"
    ON_OPEN = "on_open"
    ON_CLOSE = "on_close"
    ON_DROP = "on_drop"
