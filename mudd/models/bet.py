"""Bet model for horse race wagering.

Encapsulates all betting operations: placing, cancelling, resolving payouts,
and querying bet counts. Uses the shared currency transfer helper.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import asyncpg

from mudd.events import BalanceChangedEvent
from mudd.models.currency import (
    HOUSE_ACCOUNT_ID,
    AccountMissing,
    InsufficientFunds,
    ensure_account,
    transfer_currency,
)
from mudd.models.race import RaceHorseInfo, RaceStatus

logger = logging.getLogger(__name__)

MIN_BET = 5


class BetError(StrEnum):
    """Error codes for betting operations."""

    RACE_NOT_ACCEPTING_BETS = "race_not_accepting_bets"
    HORSE_NOT_IN_RACE = "horse_not_in_race"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    AMOUNT_TOO_LOW = "amount_too_low"
    NO_BET_TO_CANCEL = "no_bet_to_cancel"
    NO_CURRENCY_ACCOUNT = "no_currency_account"


@dataclass(frozen=True, slots=True)
class BetResult:
    """Result of a bet operation."""

    success: bool
    error: BetError | None = None
    amount: int = 0
    horse_name: str = ""
    new_balance: int = 0
    displayed_payout: float = 0.0
    balance_event: BalanceChangedEvent | None = None


@dataclass(frozen=True, slots=True)
class PayoutRecord:
    """Record of a single bet's payout resolution."""

    user_id: int
    horse_id: str
    horse_name: str
    amount_bet: int
    payout: int
    displayed_payout: float


class Bet:
    """Betting operations for horse races.

    All methods are classmethods — no instances are constructed.
    """

    @classmethod
    async def place(
        cls,
        pool: asyncpg.Pool,
        race_id: int,
        user_id: int,
        horse_id: str,
        amount: int,
        displayed_payout: float,
    ) -> BetResult:
        """Place or update a bet atomically with currency transfer.

        If the user already has a bet on this horse, computes the delta
        and adjusts the currency transfer accordingly.
        """
        if amount < MIN_BET:
            return BetResult(success=False, error=BetError.AMOUNT_TOO_LOW)

        async with pool.acquire() as conn, conn.transaction():
            # Lock race row to verify status
            race_row = await conn.fetchrow(
                "SELECT status FROM races WHERE id = $1 FOR UPDATE",
                race_id,
            )
            if race_row is None or race_row["status"] != RaceStatus.ANNOUNCING:
                return BetResult(success=False, error=BetError.RACE_NOT_ACCEPTING_BETS)

            # Verify horse is in this race
            horse_row = await conn.fetchrow(
                """
                SELECT h.name
                FROM races r,
                     jsonb_array_elements(r.odds_snapshot) AS e(value)
                JOIN horses h ON h.id = e.value->>'horse_id'
                WHERE r.id = $1 AND e.value->>'horse_id' = $2
                """,
                race_id,
                horse_id,
            )
            if horse_row is None:
                return BetResult(success=False, error=BetError.HORSE_NOT_IN_RACE)
            horse_name: str = horse_row["name"]

            # Check for existing bet on this horse
            existing = await conn.fetchrow(
                "SELECT amount FROM bets"
                " WHERE race_id = $1 AND user_id = $2 AND horse_id = $3",
                race_id,
                user_id,
                horse_id,
            )
            existing_amount = existing["amount"] if existing else 0
            delta = amount - existing_amount

            if delta == 0:
                # No change needed — return current state
                player_row = await conn.fetchrow(
                    "SELECT balance FROM currency_accounts WHERE user_id = $1",
                    user_id,
                )
                return BetResult(
                    success=True,
                    amount=amount,
                    horse_name=horse_name,
                    new_balance=player_row["balance"] if player_row else 0,
                    displayed_payout=displayed_payout,
                )

            # Ensure player has a currency account
            await ensure_account(conn, user_id)

            # Transfer currency (direction depends on delta sign)
            if delta > 0:
                memo = f"Bet on {horse_name} (Race #{race_id})"
                try:
                    outcome = await transfer_currency(
                        conn,
                        from_id=user_id,
                        to_id=HOUSE_ACCOUNT_ID,
                        amount=delta,
                        memo=memo,
                    )
                except AccountMissing:
                    return BetResult(success=False, error=BetError.NO_CURRENCY_ACCOUNT)
                except InsufficientFunds:
                    return BetResult(success=False, error=BetError.INSUFFICIENT_FUNDS)
                new_player_balance = outcome.from_balance
            else:
                refund = -delta
                memo = f"Bet adjustment refund for {horse_name} (Race #{race_id})"
                try:
                    outcome = await transfer_currency(
                        conn,
                        from_id=HOUSE_ACCOUNT_ID,
                        to_id=user_id,
                        amount=refund,
                        memo=memo,
                        require_funds=False,
                    )
                except AccountMissing:
                    return BetResult(success=False, error=BetError.NO_CURRENCY_ACCOUNT)
                new_player_balance = outcome.to_balance

            # Upsert bet row
            if existing:
                await conn.execute(
                    "UPDATE bets SET amount = $1"
                    " WHERE race_id = $2 AND user_id = $3 AND horse_id = $4",
                    amount,
                    race_id,
                    user_id,
                    horse_id,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO bets (race_id, user_id, horse_id, amount)
                    VALUES ($1, $2, $3, $4)
                    """,
                    race_id,
                    user_id,
                    horse_id,
                    amount,
                )

        # Emit event outside transaction
        balance_event = BalanceChangedEvent(
            user_id=user_id,
            new_balance=new_player_balance,
            delta=-delta,
            memo=memo,
        )

        return BetResult(
            success=True,
            amount=amount,
            horse_name=horse_name,
            new_balance=new_player_balance,
            displayed_payout=displayed_payout,
            balance_event=balance_event,
        )

    @classmethod
    async def cancel(
        cls,
        pool: asyncpg.Pool,
        race_id: int,
        user_id: int,
        horse_id: str,
    ) -> BetResult:
        """Cancel a bet and refund the player."""
        async with pool.acquire() as conn, conn.transaction():
            # Lock race row to verify status
            race_row = await conn.fetchrow(
                "SELECT status FROM races WHERE id = $1 FOR UPDATE",
                race_id,
            )
            if race_row is None or race_row["status"] != RaceStatus.ANNOUNCING:
                return BetResult(success=False, error=BetError.RACE_NOT_ACCEPTING_BETS)

            # Delete bet and get amount
            bet_row = await conn.fetchrow(
                """
                DELETE FROM bets
                WHERE race_id = $1 AND user_id = $2 AND horse_id = $3
                RETURNING amount
                """,
                race_id,
                user_id,
                horse_id,
            )
            if bet_row is None:
                return BetResult(success=False, error=BetError.NO_BET_TO_CANCEL)

            refund: int = bet_row["amount"]

            # Get horse name
            horse_row = await conn.fetchrow(
                "SELECT name FROM horses WHERE id = $1", horse_id
            )
            horse_name = horse_row["name"] if horse_row else horse_id

            memo = f"Bet cancelled on {horse_name} (Race #{race_id})"
            try:
                outcome = await transfer_currency(
                    conn,
                    from_id=HOUSE_ACCOUNT_ID,
                    to_id=user_id,
                    amount=refund,
                    memo=memo,
                    require_funds=False,
                )
            except AccountMissing:
                return BetResult(success=False, error=BetError.NO_CURRENCY_ACCOUNT)
            new_player_balance = outcome.to_balance

        # Emit event outside transaction
        balance_event = BalanceChangedEvent(
            user_id=user_id,
            new_balance=new_player_balance,
            delta=refund,
            memo=memo,
        )

        return BetResult(
            success=True,
            amount=refund,
            horse_name=horse_name,
            new_balance=new_player_balance,
            balance_event=balance_event,
        )

    @classmethod
    async def resolve_payouts(
        cls,
        pool: asyncpg.Pool,
        race_id: int,
        winner_horse_id: str,
        odds: list[RaceHorseInfo],
    ) -> tuple[list[PayoutRecord], list[BalanceChangedEvent]]:
        """Resolve all bets for a finished race.

        Winning bets get payout = amount * displayed_payout.
        Losing bets get payout = 0.
        All operations run in a single transaction with batch updates.

        Returns:
            Tuple of (payout records, balance change events for wallet notifications).
        """
        odds_map = {o.id: o.displayed_payout for o in odds}
        horse_names = {o.id: o.name for o in odds}

        # Fetch all bets for this race
        rows = await pool.fetch(
            "SELECT id, user_id, horse_id, amount FROM bets WHERE race_id = $1",
            race_id,
        )
        if not rows:
            return [], []

        # Compute payouts in Python
        bet_ids: list[int] = []
        payout_amounts: list[int] = []
        payouts: list[PayoutRecord] = []
        # Winning bets grouped by user for batch transfer
        winner_payouts: dict[int, tuple[int, str]] = {}  # user_id -> (total, memo)

        for row in rows:
            bet_id: int = row["id"]
            uid: int = row["user_id"]
            horse_id: str = row["horse_id"]
            amount_bet: int = row["amount"]
            dp = odds_map.get(horse_id, 0.0)
            h_name = horse_names.get(horse_id, horse_id)

            payout = int(amount_bet * dp) if horse_id == winner_horse_id else 0

            bet_ids.append(bet_id)
            payout_amounts.append(payout)
            payouts.append(
                PayoutRecord(
                    user_id=uid,
                    horse_id=horse_id,
                    horse_name=h_name,
                    amount_bet=amount_bet,
                    payout=payout,
                    displayed_payout=dp,
                )
            )

            if payout > 0:
                existing_total, _ = winner_payouts.get(uid, (0, ""))
                winner_payouts[uid] = (
                    existing_total + payout,
                    f"Race #{race_id} payout: {h_name} won!",
                )

        balance_events: list[BalanceChangedEvent] = []

        async with pool.acquire() as conn, conn.transaction():
            # Batch update all bet payout values
            await conn.execute(
                "UPDATE bets AS b SET payout = v.payout "
                "FROM (SELECT unnest($1::int[]) AS id,"
                " unnest($2::int[]) AS payout) AS v "
                "WHERE b.id = v.id",
                bet_ids,
                payout_amounts,
            )

            if not winner_payouts:
                return payouts, []

            # Process winner payouts using shared transfer helper
            for uid, (total_payout, memo) in sorted(winner_payouts.items()):
                try:
                    outcome = await transfer_currency(
                        conn,
                        from_id=HOUSE_ACCOUNT_ID,
                        to_id=uid,
                        amount=total_payout,
                        memo=memo,
                        require_funds=False,
                    )
                except AccountMissing as exc:
                    logger.warning(
                        "Skipping payout for user %d (race #%d): %s",
                        uid,
                        race_id,
                        exc,
                    )
                    continue

                balance_events.append(
                    BalanceChangedEvent(
                        user_id=uid,
                        new_balance=outcome.to_balance,
                        delta=total_payout,
                        memo=memo,
                    )
                )

        return payouts, balance_events

    @classmethod
    async def count(cls, pool: asyncpg.Pool, race_id: int) -> int:
        """Get the number of bets placed on a race."""
        count: int = await pool.fetchval(
            "SELECT COUNT(*) FROM bets WHERE race_id = $1", race_id
        )
        return count
