"""User model with database access methods."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Self
from uuid import UUID

import asyncpg

from mudd.events import (
    BalanceChangedEvent,
    BroadcastEvent,
    FocusChangedEvent,
    Observer,
    UserLocationSyncEvent,
    UserMovedEvent,
)
from mudd.models.entity import EntityInstance
from mudd.models.room import Room
from mudd.models.skills import UserSkill

FOCUS_TIMEOUT_MINUTES = 5
STARTING_BALANCE = 1000
HOUSE_ACCOUNT_ID = 0


class TransferError(Enum):
    """Error types for currency transfer operations."""

    INSUFFICIENT_FUNDS = auto()
    NO_SENDER_ACCOUNT = auto()
    NO_RECIPIENT_ACCOUNT = auto()


@dataclass(frozen=True)
class TransferResult:
    """Result of a currency transfer operation."""

    success: bool
    sender_balance: int
    recipient_balance: int
    error: TransferError | None = None


@dataclass(frozen=True)
class FocusContext:
    """Value object representing a user's current focus state.

    Focus establishes a "modal" interaction context where autocomplete
    prioritizes entities accessible through the focused entity.

    This is a pure value object with no database access methods.
    """

    current_container: EntityInstance
    updated_at: datetime

    async def contains(self, entity: EntityInstance) -> bool:
        contents = {e.instance_id for e in await self.current_container.get_contents()}
        focused_entity_ids = {self.current_container.instance_id} | contents

        return entity.instance_id in focused_entity_ids


@dataclass(frozen=True)
class User:
    """User model with database access methods.

    Instances are immutable. Mutation methods (move_to) update the
    database and return new instances.
    """

    id: int
    current_room: str
    display_name: str
    _pool: asyncpg.Pool = field(repr=False, compare=False)
    _observers: tuple[Observer, ...] = field(
        repr=False, compare=False, default_factory=tuple
    )

    @property
    def mention(self) -> str:
        """Discord mention string for this user."""
        return f"<@{self.id}>"

    def with_observers(self, *observers: Observer) -> Self:
        """Return a new instance with additional observers appended.

        Args:
            *observers: Observer callbacks to add

        Returns:
            New User with observers appended
        """
        return replace(self, _observers=self._observers + observers)

    @classmethod
    async def get(cls, pool: asyncpg.Pool, user_id: int) -> User | None:
        """Get user by Discord ID.

        Args:
            pool: Database connection pool
            user_id: Discord user snowflake ID

        Returns:
            User model instance, or None if not found
        """
        row = await pool.fetchrow(
            "SELECT id, current_room, display_name FROM users WHERE id = $1",
            user_id,
        )

        if row is None:
            return None

        return cls(
            id=row["id"],
            current_room=row["current_room"],
            display_name=row["display_name"],
            _pool=pool,
        )

    @classmethod
    async def get_or_create(cls, pool: asyncpg.Pool, user_id: int) -> User:
        """Get user by Discord ID, creating with default room if missing.

        Args:
            pool: Database connection pool
            user_id: Discord user snowflake ID

        Returns:
            User model instance (existing or newly created)
        """
        default = await Room.get_default(pool)
        if default is None:
            # No default room configured, try to get existing user
            existing = await cls.get(pool, user_id)
            if existing:
                return existing
            raise ValueError("No default room configured and user does not exist")

        row = await pool.fetchrow(
            """
            INSERT INTO users (id, current_room)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id
            RETURNING id, current_room, display_name
            """,
            user_id,
            default.id,
        )

        user_id = row["id"]
        await UserSkill.create_defaults(pool, user_id)

        return cls(
            id=user_id,
            current_room=row["current_room"],
            display_name=row["display_name"],
            _pool=pool,
        )

    @classmethod
    async def create_or_update(
        cls, pool: asyncpg.Pool, user_id: int, display_name: str, default_room: str
    ) -> User:
        """Create or update a user with display_name.

        For new users, creates them in the default_room.
        For existing users, updates their display_name (keeps current_room).

        Args:
            pool: Database connection pool
            user_id: Discord user snowflake ID
            display_name: User's current Discord display name
            default_room: Room to assign new users to

        Returns:
            User model instance
        """
        row = await pool.fetchrow(
            """
            INSERT INTO users (id, current_room, display_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET display_name = $3
            RETURNING id, current_room, display_name
            """,
            user_id,
            default_room,
            display_name,
        )

        # row can't be None here since we're doing an INSERT with RETURNING
        assert row is not None

        user_id = row["id"]
        await UserSkill.create_defaults(pool, user_id)

        return cls(
            id=user_id,
            current_room=row["current_room"],
            display_name=row["display_name"],
            _pool=pool,
        )

    async def get_room(self) -> Room:
        """Get the user's current room.

        Returns:
            Room model instance

        Raises:
            ValueError: If room not found (should never happen with FK constraint)
        """
        room = await Room.get(self._pool, self.current_room)
        if room is None:
            raise ValueError(f"Room not found: {self.current_room}")
        return room

    async def get_inventory(self) -> list[EntityInstance]:
        """Get all entities in the user's inventory.

        Returns:
            List of EntityInstance objects owned by this user
        """
        from mudd.models.entity import EntityInstance

        return await EntityInstance.get_by_owner(self._pool, self.id)

    async def has_entity_by_tag(self, tag: str) -> bool:
        """Check if the user has an entity with the given tag in their inventory.

        Args:
            tag: Entity tag to search for

        Returns:
            True if the user owns at least one entity instance with this tag
        """
        row = await self._pool.fetchrow(
            """
            SELECT 1 FROM entity_instances ei
            JOIN entity_tags et ON et.entity_id = ei.entity_id
            WHERE ei.owner_id = $1 AND et.tag = $2
            LIMIT 1
            """,
            self.id,
            tag,
        )
        return row is not None

    async def get_focus(self) -> FocusContext | None:
        """Get the user's current focus context, if any.

        Returns None if:
        - User has no focus established
        - Focus is in different room (stale)
        - Focus expired (>5 minutes old)

        Stale/expired focus is automatically deleted.

        Returns:
            Active FocusContext or None
        """
        row = await self._pool.fetchrow(
            """
            SELECT uf.entity_instance_id, uf.updated_at
            FROM user_focus uf
            JOIN entity_instances ei ON ei.id = uf.entity_instance_id
            WHERE uf.user_id = $1 AND ei.room = $2
            """,
            self.id,
            self.current_room,
        )

        if not row:
            return None

        # Check timeout
        cutoff = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES)
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        if updated_at < cutoff:
            # Lazy cleanup: delete and return None
            await self._pool.execute(
                "DELETE FROM user_focus WHERE user_id = $1", self.id
            )
            return None

        entity = await EntityInstance.get(self._pool, row["entity_instance_id"])
        if not entity:
            return None

        return FocusContext(
            current_container=entity,
            updated_at=updated_at,
        )

    @classmethod
    async def get_active_focus_id(
        cls, pool: asyncpg.Pool, user_id: int, room_id: str
    ) -> UUID | None:
        """Get the focused entity instance ID without loading the full entity.

        Returns None if user has no focus, focus is in a different room,
        or focus has expired.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            room_id: Expected room ID (must match entity's room)

        Returns:
            UUID of focused entity instance, or None
        """
        row = await pool.fetchrow(
            """
            SELECT uf.entity_instance_id, uf.updated_at
            FROM user_focus uf
            JOIN entity_instances ei ON ei.id = uf.entity_instance_id
            WHERE uf.user_id = $1 AND ei.room = $2
            """,
            user_id,
            room_id,
        )

        if not row:
            return None

        cutoff = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES)
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        if updated_at < cutoff:
            return None

        return row["entity_instance_id"]

    async def set_focus(self, entity_instance_id: UUID) -> None:
        """Establish focus on an entity instance.

        Args:
            entity_instance_id: UUID of the entity instance to focus on
        """
        await self._pool.execute(
            """
            INSERT INTO user_focus (user_id, entity_instance_id, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                entity_instance_id = EXCLUDED.entity_instance_id,
                updated_at = EXCLUDED.updated_at
            """,
            self.id,
            entity_instance_id,
        )
        for observer in self._observers:
            observer.notify(FocusChangedEvent(user_id=self.id))

    async def clear_focus(self) -> None:
        """Clear user's focus."""
        await self._pool.execute("DELETE FROM user_focus WHERE user_id = $1", self.id)
        for observer in self._observers:
            observer.notify(FocusChangedEvent(user_id=self.id))

    async def refresh_focus(self) -> None:
        """Update the timestamp on user's focus to prevent timeout."""
        await self._pool.execute(
            "UPDATE user_focus SET updated_at = now() WHERE user_id = $1",
            self.id,
        )

    async def get_balance(self) -> int:
        """Get the user's currency balance.

        Returns:
            Balance in yen (0 if no account exists)
        """
        row = await self._pool.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1",
            self.id,
        )

        if row is None:
            return 0

        return row["balance"]

    async def credit_from_house(self, amount: int, memo: str) -> int:
        """Credit currency from the house account to this user.

        Uses double-entry ledger: debit house (user_id=0), credit player.
        Creates the player's currency account if it doesn't exist.

        Args:
            amount: Amount to credit (must be positive)
            memo: Transaction memo

        Returns:
            New balance after credit
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")

        async with self._pool.acquire() as conn, conn.transaction():
            # Upsert player's currency account (creates if missing)
            await conn.execute(
                """
                INSERT INTO currency_accounts (user_id, balance)
                VALUES ($1, 0)
                ON CONFLICT (user_id) DO NOTHING
                """,
                self.id,
            )

            # Lock accounts in sorted order (house=0 always first)
            house_row = await conn.fetchrow(
                "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
                HOUSE_ACCOUNT_ID,
            )
            player_row = await conn.fetchrow(
                "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
                self.id,
            )

            if house_row is None:
                raise ValueError("House account does not exist")
            if player_row is None:
                raise ValueError("Player account does not exist")

            # Create transaction + ledger entries
            tx_row = await conn.fetchrow(
                "INSERT INTO currency_transactions (memo) VALUES ($1) RETURNING id",
                memo,
            )
            await conn.execute(
                """
                INSERT INTO currency_ledger (transaction_id, account_id, amount)
                VALUES ($1, $2, $3), ($1, $4, $5)
                """,
                tx_row["id"],
                HOUSE_ACCOUNT_ID,
                -amount,
                self.id,
                amount,
            )

            # Update balances
            new_balance = player_row["balance"] + amount
            await conn.execute(
                "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                house_row["balance"] - amount,
                HOUSE_ACCOUNT_ID,
            )
            await conn.execute(
                "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                new_balance,
                self.id,
            )

        # Emit event (outside transaction)
        for observer in self._observers:
            observer.notify(BalanceChangedEvent(self.id, new_balance, amount, memo))

        return new_balance

    @classmethod
    async def create_if_not_exists(
        cls, pool: asyncpg.Pool, user_id: int, default_room: str
    ) -> None:
        """Ensure a user row exists, inserting with default_room if missing.

        Unlike get_or_create, this uses ON CONFLICT DO NOTHING, doesn't require
        display_name, and returns nothing. Used by inventory setup where we just
        need the FK to exist.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            default_room: Room to assign if creating a new user
        """
        await pool.execute(
            """
            INSERT INTO users (id, current_room)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
            """,
            user_id,
            default_room,
        )
        await UserSkill.create_defaults(pool, user_id)

    @classmethod
    async def get_current_room(cls, pool: asyncpg.Pool, user_id: int) -> str | None:
        """Get the room ID of a user's current location.

        Args:
            pool: Database connection pool
            user_id: Discord user ID

        Returns:
            Room ID string, or None if user not found
        """
        row = await pool.fetchrow(
            "SELECT current_room FROM users WHERE id = $1",
            user_id,
        )
        return row["current_room"] if row else None

    @classmethod
    async def create_currency_account(
        cls, pool: asyncpg.Pool, user_id: int, starting_balance: int
    ) -> None:
        """Ensure a currency account exists for a user.

        Uses ON CONFLICT DO NOTHING so existing accounts are preserved.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            starting_balance: Balance for new accounts
        """
        await pool.execute(
            """
            INSERT INTO currency_accounts (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
            starting_balance,
        )

    @classmethod
    async def update_wallet_instance(
        cls, pool: asyncpg.Pool, user_id: int, wallet_instance_id: str
    ) -> None:
        """Set the wallet entity instance ID on a user's currency account.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            wallet_instance_id: UUID string of the wallet EntityInstance
        """
        await pool.execute(
            """
            UPDATE currency_accounts
            SET wallet_instance_id = $2
            WHERE user_id = $1
            """,
            user_id,
            wallet_instance_id,
        )

    @classmethod
    async def get_players_in_room(cls, pool: asyncpg.Pool, room_id: str) -> list[User]:
        """Get all players in a room.

        Args:
            pool: Database connection pool
            room_id: Room ID to query

        Returns:
            List of User objects for players in the room
        """
        rows = await pool.fetch(
            "SELECT id, current_room, display_name FROM users WHERE current_room = $1",
            room_id,
        )
        return [
            cls(
                id=row["id"],
                current_room=row["current_room"],
                display_name=row["display_name"],
                _pool=pool,
            )
            for row in rows
        ]

    async def move_to(self, room_id: str, *, guild_id: int) -> User:
        """Move the user to a different room.

        Updates the database, clears focus, and returns a new User instance.
        Emits UserMovedEvent (game logic) and UserLocationSyncEvent (Discord sync).

        Args:
            room_id: Target room ID
            guild_id: Discord guild ID for event emission

        Returns:
            New User instance with updated location
        """
        from_room = self.current_room

        # Clear focus when moving rooms (per ADR 0003)
        await self.clear_focus()

        await self._pool.execute(
            "UPDATE users SET current_room = $2 WHERE id = $1",
            self.id,
            room_id,
        )

        new_user = replace(self, current_room=room_id)

        # Emit game event (for other observers that care about movement)
        for observer in new_user._observers:
            observer.notify(UserMovedEvent(self.id, from_room, room_id, guild_id))

        # Emit infra event (permission sync)
        for observer in new_user._observers:
            observer.notify(
                UserLocationSyncEvent(self.id, from_room, room_id, guild_id)
            )

        return new_user

    async def get_wallet(self) -> EntityInstance | None:
        """Get user's wallet instance, if any.

        Returns:
            EntityInstance for the wallet, or None if no wallet exists
        """
        row = await self._pool.fetchrow(
            """
            SELECT wallet_instance_id FROM currency_accounts
            WHERE user_id = $1 AND wallet_instance_id IS NOT NULL
            """,
            self.id,
        )

        if row is None:
            return None

        return await EntityInstance.get(self._pool, row["wallet_instance_id"])

    async def transfer_currency_to(
        self, recipient: User, amount: int, memo: str
    ) -> TransferResult:
        """Transfer currency to another user.

        Returns TransferResult with success status, balances, and error if any.
        Emits BalanceChangedEvent for both users on success.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if self.id == recipient.id:
            raise ValueError("Cannot transfer to self")

        # Sort IDs to prevent deadlocks
        first_id, second_id = sorted([self.id, recipient.id])

        async with self._pool.acquire() as conn, conn.transaction():
            # Lock accounts in sorted order
            first_row = await conn.fetchrow(
                "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
                first_id,
            )
            second_row = await conn.fetchrow(
                "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
                second_id,
            )

            if first_id == self.id:
                sender_row, recipient_row = first_row, second_row
            else:
                sender_row, recipient_row = second_row, first_row

            if sender_row is None:
                return TransferResult(
                    success=False,
                    sender_balance=0,
                    recipient_balance=recipient_row["balance"] if recipient_row else 0,
                    error=TransferError.NO_SENDER_ACCOUNT,
                )
            if recipient_row is None:
                return TransferResult(
                    success=False,
                    sender_balance=sender_row["balance"],
                    recipient_balance=0,
                    error=TransferError.NO_RECIPIENT_ACCOUNT,
                )
            if sender_row["balance"] < amount:
                return TransferResult(
                    success=False,
                    sender_balance=sender_row["balance"],
                    recipient_balance=recipient_row["balance"],
                    error=TransferError.INSUFFICIENT_FUNDS,
                )

            # Create transaction + ledger entries
            tx_row = await conn.fetchrow(
                "INSERT INTO currency_transactions (memo) VALUES ($1) RETURNING id",
                memo,
            )
            await conn.execute(
                """
                INSERT INTO currency_ledger (transaction_id, account_id, amount)
                VALUES ($1, $2, $3), ($1, $4, $5)
                """,
                tx_row["id"],
                self.id,
                -amount,
                recipient.id,
                amount,
            )

            # Update balances
            sender_new = sender_row["balance"] - amount
            recipient_new = recipient_row["balance"] + amount
            await conn.execute(
                "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                sender_new,
                self.id,
            )
            await conn.execute(
                "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                recipient_new,
                recipient.id,
            )

        # Emit events (outside transaction) with per-user memos using mentions
        sender_memo = f"Payment to {recipient.mention}"
        recipient_memo = f"Payment from {self.mention}"
        for observer in self._observers:
            observer.notify(
                BalanceChangedEvent(self.id, sender_new, -amount, sender_memo)
            )
            observer.notify(
                BalanceChangedEvent(recipient.id, recipient_new, amount, recipient_memo)
            )

        # Broadcast the payment to the channel
        amount_str = f"\u00a5{amount:,}"
        broadcast_msg = f"{self.mention} paid {amount_str} to {recipient.mention}"
        for observer in self._observers:
            observer.notify(BroadcastEvent(message=broadcast_msg))

        return TransferResult(
            success=True,
            sender_balance=sender_new,
            recipient_balance=recipient_new,
        )

    @classmethod
    async def update_display_name(
        cls, pool: asyncpg.Pool, user_id: int, display_name: str
    ) -> None:
        """Update a user's display name.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            display_name: New display name to persist
        """
        await pool.execute(
            "UPDATE users SET display_name = $2 WHERE id = $1",
            user_id,
            display_name,
        )

    @classmethod
    async def delete(cls, pool: asyncpg.Pool, user_id: int) -> None:
        """Delete a user from the database.

        CASCADE will handle related records (user_focus, user_inventory_forums, etc.)

        Args:
            pool: Database connection pool
            user_id: Discord user ID to delete
        """
        await pool.execute("DELETE FROM users WHERE id = $1", user_id)
