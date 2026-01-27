"""Currency service for managing player economy."""

import logging
from dataclasses import dataclass
from enum import Enum, auto

import asyncpg

logger = logging.getLogger(__name__)

# Starting balance for new accounts
STARTING_BALANCE = 1000

# House account user ID (for system transactions)
HOUSE_ACCOUNT_ID = 0


class TransferError(Enum):
    """Reasons a transfer can fail."""

    INVALID_AMOUNT = auto()
    INSUFFICIENT_BALANCE = auto()
    SENDER_NOT_FOUND = auto()
    RECIPIENT_NOT_FOUND = auto()
    SELF_TRANSFER = auto()
    IDEMPOTENCY_CONFLICT = auto()


@dataclass(frozen=True)
class TransferResult:
    """Result of a currency transfer."""

    success: bool
    error: TransferError | None = None
    sender_new_balance: int | None = None
    recipient_new_balance: int | None = None


class CurrencyService:
    """Manages currency accounts and transactions.

    Implements a double-entry ledger for auditability. Each transfer
    creates a transaction record with two ledger entries (debit + credit).

    Usage:
        service = CurrencyService(pool)
        await service.ensure_account(user_id)
        balance = await service.get_balance(user_id)
        result = await service.transfer(sender_id, recipient_id, 100, "Payment")
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_balance(self, user_id: int) -> int | None:
        """Get the balance for a user's currency account.

        Args:
            user_id: Discord user ID

        Returns:
            Balance in yen, or None if account doesn't exist
        """
        row = await self._pool.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1",
            user_id,
        )
        if row is None:
            return None
        return row["balance"]

    async def ensure_account(
        self,
        user_id: int,
        starting_balance: int = STARTING_BALANCE,
    ) -> bool:
        """Ensure a currency account exists for the user.

        Creates a new account with the starting balance if one doesn't exist.

        Args:
            user_id: Discord user ID
            starting_balance: Initial balance for new accounts

        Returns:
            True if a new account was created, False if account already existed
        """
        result = await self._pool.execute(
            """
            INSERT INTO currency_accounts (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
            starting_balance,
        )
        # "INSERT 0 1" means a row was inserted
        return result == "INSERT 0 1"

    async def link_wallet(self, user_id: int, wallet_instance_id: str) -> None:
        """Link a wallet instance to a currency account.

        Args:
            user_id: Discord user ID
            wallet_instance_id: UUID of the wallet entity instance
        """
        await self._pool.execute(
            """
            UPDATE currency_accounts
            SET wallet_instance_id = $2
            WHERE user_id = $1
            """,
            user_id,
            wallet_instance_id,
        )

    async def get_wallet_instance_id(self, user_id: int) -> str | None:
        """Get the wallet instance ID for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Wallet instance UUID string, or None if no account or no wallet
        """
        row = await self._pool.fetchrow(
            "SELECT wallet_instance_id FROM currency_accounts WHERE user_id = $1",
            user_id,
        )
        if row is None or row["wallet_instance_id"] is None:
            return None
        return str(row["wallet_instance_id"])

    async def transfer(
        self,
        sender_id: int,
        recipient_id: int,
        amount: int,
        memo: str,
        idempotency_key: str | None = None,
    ) -> TransferResult:
        """Transfer currency from one account to another.

        Implements atomic transfer with double-entry ledger entries.
        Accounts are locked in sorted user_id order to prevent deadlocks.

        Args:
            sender_id: Discord user ID of sender
            recipient_id: Discord user ID of recipient
            amount: Amount to transfer (must be positive)
            memo: Description of the transaction
            idempotency_key: Optional key for idempotent retries

        Returns:
            TransferResult with success status and new balances
        """
        # Validate amount
        if amount <= 0:
            return TransferResult(success=False, error=TransferError.INVALID_AMOUNT)

        # Prevent self-transfer
        if sender_id == recipient_id:
            return TransferResult(success=False, error=TransferError.SELF_TRANSFER)

        # Sort account IDs to prevent deadlocks
        first_id, second_id = sorted([sender_id, recipient_id])

        async with self._pool.acquire() as conn, conn.transaction():
            # Lock both accounts in sorted order
            first_row = await conn.fetchrow(
                """
                SELECT user_id, balance FROM currency_accounts
                WHERE user_id = $1
                FOR UPDATE
                """,
                first_id,
            )
            second_row = await conn.fetchrow(
                """
                SELECT user_id, balance FROM currency_accounts
                WHERE user_id = $1
                FOR UPDATE
                """,
                second_id,
            )

            # Map back to sender/recipient
            if first_id == sender_id:
                sender_row, recipient_row = first_row, second_row
            else:
                sender_row, recipient_row = second_row, first_row

            # Check accounts exist
            if sender_row is None:
                return TransferResult(
                    success=False, error=TransferError.SENDER_NOT_FOUND
                )
            if recipient_row is None:
                return TransferResult(
                    success=False, error=TransferError.RECIPIENT_NOT_FOUND
                )

            # Check sufficient balance
            if sender_row["balance"] < amount:
                return TransferResult(
                    success=False, error=TransferError.INSUFFICIENT_BALANCE
                )

            # Create transaction record
            try:
                tx_row = await conn.fetchrow(
                    """
                    INSERT INTO currency_transactions (memo, idempotency_key)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    memo,
                    idempotency_key,
                )
            except asyncpg.UniqueViolationError:
                # Idempotency key already used
                return TransferResult(
                    success=False, error=TransferError.IDEMPOTENCY_CONFLICT
                )

            tx_id = tx_row["id"]

            # Create ledger entries (debit sender, credit recipient)
            await conn.execute(
                """
                INSERT INTO currency_ledger (transaction_id, account_id, amount)
                VALUES ($1, $2, $3), ($1, $4, $5)
                """,
                tx_id,
                sender_id,
                -amount,  # debit
                recipient_id,
                amount,  # credit
            )

            # Update balances
            sender_new_balance = sender_row["balance"] - amount
            recipient_new_balance = recipient_row["balance"] + amount

            await conn.execute(
                "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                sender_new_balance,
                sender_id,
            )
            await conn.execute(
                "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                recipient_new_balance,
                recipient_id,
            )

            logger.info(
                f"Transfer: {sender_id} -> {recipient_id}, amount={amount}, "
                f"memo='{memo}'"
            )

            return TransferResult(
                success=True,
                sender_new_balance=sender_new_balance,
                recipient_new_balance=recipient_new_balance,
            )
