"""Shared currency ledger operations.

Encapsulates the double-entry bookkeeping pattern used across
betting, credit, and transfer operations.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

HOUSE_ACCOUNT_ID = 0


class AccountMissing(Exception):
    """A required currency account does not exist."""

    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        super().__init__(f"Currency account {account_id} does not exist")


class InsufficientFunds(Exception):
    """Source account has insufficient balance for the transfer."""

    def __init__(self, account_id: int, balance: int, amount: int) -> None:
        self.account_id = account_id
        self.balance = balance
        self.amount = amount
        super().__init__(f"Account {account_id} has balance {balance}, need {amount}")


@dataclass(frozen=True, slots=True)
class TransferOutcome:
    """Result of a currency transfer."""

    from_balance: int
    to_balance: int


async def ensure_account(conn: asyncpg.Connection, user_id: int) -> None:
    """Create a currency account with zero balance if it doesn't exist."""
    await conn.execute(
        "INSERT INTO currency_accounts (user_id, balance) "
        "VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING",
        user_id,
    )


async def transfer_currency(
    conn: asyncpg.Connection,
    *,
    from_id: int,
    to_id: int,
    amount: int,
    memo: str,
    require_funds: bool = True,
) -> TransferOutcome:
    """Perform a double-entry currency transfer within an active transaction.

    Locks accounts in sorted ID order, creates a transaction with ledger
    entries, and updates both balances.

    Args:
        conn: Connection with an active transaction.
        from_id: Account ID to debit.
        to_id: Account ID to credit.
        amount: Positive transfer amount.
        memo: Transaction memo.
        require_funds: If True (default), raises InsufficientFunds when
            the source account cannot cover the transfer. Set to False
            for house-sourced transfers where negative balance is acceptable.

    Returns:
        TransferOutcome with new balances for both accounts.

    Raises:
        AccountMissing: If either account doesn't exist.
        InsufficientFunds: If require_funds and source balance < amount.
        ValueError: If amount is not positive.
    """
    if amount <= 0:
        raise ValueError("Transfer amount must be positive")

    # Lock accounts in sorted order to prevent deadlocks
    first_id, second_id = sorted([from_id, to_id])
    first_row = await conn.fetchrow(
        "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
        first_id,
    )
    second_row = await conn.fetchrow(
        "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
        second_id,
    )

    if first_row is None:
        raise AccountMissing(first_id)
    if second_row is None:
        raise AccountMissing(second_id)

    if first_id == from_id:
        from_balance: int = first_row["balance"]
        to_balance: int = second_row["balance"]
    else:
        from_balance = second_row["balance"]
        to_balance = first_row["balance"]

    if require_funds and from_balance < amount:
        raise InsufficientFunds(from_id, from_balance, amount)

    # Create transaction + ledger entries
    tx_id: int = await conn.fetchval(
        "INSERT INTO currency_transactions (memo) VALUES ($1) RETURNING id",
        memo,
    )
    await conn.execute(
        """
        INSERT INTO currency_ledger (transaction_id, account_id, amount)
        VALUES ($1, $2, $3), ($1, $4, $5)
        """,
        tx_id,
        from_id,
        -amount,
        to_id,
        amount,
    )

    # Update balances
    from_new = from_balance - amount
    to_new = to_balance + amount
    await conn.execute(
        "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
        from_new,
        from_id,
    )
    await conn.execute(
        "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
        to_new,
        to_id,
    )

    return TransferOutcome(from_balance=from_new, to_balance=to_new)
