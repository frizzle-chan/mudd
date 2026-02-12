"""Betting logic for horse races.

Core functions for placing, cancelling, and resolving bets using
the double-entry currency ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import asyncpg

from mudd.events import BalanceChangedEvent
from mudd.models.user import HOUSE_ACCOUNT_ID
from mudd.racing.persistence import RaceStatus

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
class ActiveRace:
    """Lightweight projection of an active race."""

    id: int
    status: RaceStatus


@dataclass(frozen=True, slots=True)
class RaceHorseInfo:
    """Horse info for betting display."""

    id: str
    name: str
    displayed_payout: float


@dataclass(frozen=True, slots=True)
class PayoutRecord:
    """Record of a single bet's payout resolution."""

    user_id: int
    horse_id: str
    horse_name: str
    amount_bet: int
    payout: int
    displayed_payout: float


async def get_active_race(pool: asyncpg.Pool) -> ActiveRace | None:
    """Return the active race (ANNOUNCING or RUNNING), if any."""
    row = await pool.fetchrow(
        "SELECT id, status FROM races"
        " WHERE status IN ('announcing', 'running')"
        " ORDER BY id DESC LIMIT 1"
    )
    if row is None:
        return None
    return ActiveRace(id=row["id"], status=RaceStatus(row["status"]))


async def get_race_horses(pool: asyncpg.Pool, race_id: int) -> list[RaceHorseInfo]:
    """Get horses in a race with display names and odds from odds_snapshot."""
    rows = await pool.fetch(
        """
        SELECT e.value->>'horse_id' AS horse_id,
               h.name,
               (e.value->>'displayed_payout')::float AS displayed_payout
        FROM races r,
             jsonb_array_elements(r.odds_snapshot) AS e(value)
        JOIN horses h ON h.id = e.value->>'horse_id'
        WHERE r.id = $1
        ORDER BY h.name
        """,
        race_id,
    )
    return [
        RaceHorseInfo(
            id=row["horse_id"],
            name=row["name"],
            displayed_payout=row["displayed_payout"],
        )
        for row in rows
    ]


async def place_bet(
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
    horse_name = ""

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
        horse_name = horse_row["name"]

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

        # Upsert player's currency account (creates if missing)
        await conn.execute(
            """
            INSERT INTO currency_accounts (user_id, balance)
            VALUES ($1, 0)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
        )

        # Lock accounts in sorted order (house=0 always first)
        house_row = await conn.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
            HOUSE_ACCOUNT_ID,
        )
        player_row = await conn.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
            user_id,
        )

        if house_row is None:
            raise ValueError("House account does not exist")
        if player_row is None:
            return BetResult(success=False, error=BetError.NO_CURRENCY_ACCOUNT)

        if delta > 0 and player_row["balance"] < delta:
            return BetResult(success=False, error=BetError.INSUFFICIENT_FUNDS)

        # Create transaction + ledger entries
        if delta > 0:
            # Player pays more: debit player, credit house
            memo = f"Bet on {horse_name} (Race #{race_id})"
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
                user_id,
                -delta,
                HOUSE_ACCOUNT_ID,
                delta,
            )
        else:
            # Player gets refund (delta is negative, so -delta is positive)
            refund = -delta
            memo = f"Bet adjustment refund for {horse_name} (Race #{race_id})"
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
                -refund,
                user_id,
                refund,
            )

        # Update balances
        new_player_balance = player_row["balance"] - delta
        new_house_balance = house_row["balance"] + delta
        await conn.execute(
            "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
            new_house_balance,
            HOUSE_ACCOUNT_ID,
        )
        await conn.execute(
            "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
            new_player_balance,
            user_id,
        )

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

    # Emit event outside transaction (matches User.credit_from_house pattern)
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


async def cancel_bet(
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

        refund = bet_row["amount"]

        # Get horse name
        horse_row = await conn.fetchrow(
            "SELECT name FROM horses WHERE id = $1", horse_id
        )
        horse_name = horse_row["name"] if horse_row else horse_id

        # Lock accounts in sorted order (house=0 always first)
        house_row = await conn.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
            HOUSE_ACCOUNT_ID,
        )
        player_row = await conn.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1 FOR UPDATE",
            user_id,
        )

        if house_row is None:
            raise ValueError("House account does not exist")
        if player_row is None:
            return BetResult(success=False, error=BetError.NO_CURRENCY_ACCOUNT)

        # Create refund transaction
        memo = f"Bet cancelled on {horse_name} (Race #{race_id})"
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
            -refund,
            user_id,
            refund,
        )

        # Update balances
        new_player_balance = player_row["balance"] + refund
        new_house_balance = house_row["balance"] - refund
        await conn.execute(
            "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
            new_house_balance,
            HOUSE_ACCOUNT_ID,
        )
        await conn.execute(
            "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
            new_player_balance,
            user_id,
        )

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


async def resolve_payouts(
    pool: asyncpg.Pool,
    race_id: int,
    winner_horse_id: str,
    odds: list[RaceHorseInfo],
) -> tuple[list[PayoutRecord], list[BalanceChangedEvent]]:
    """Resolve all bets for a finished race.

    Winning bets get payout = amount * displayed_payout.
    Losing bets get payout = 0.
    All bet rows are updated with their payout.

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

    payouts: list[PayoutRecord] = []
    balance_events: list[BalanceChangedEvent] = []

    for row in rows:
        bet_id = row["id"]
        user_id = row["user_id"]
        horse_id = row["horse_id"]
        amount_bet = row["amount"]
        dp = odds_map.get(horse_id, 0.0)
        h_name = horse_names.get(horse_id, horse_id)

        payout = int(amount_bet * dp) if horse_id == winner_horse_id else 0

        payouts.append(
            PayoutRecord(
                user_id=user_id,
                horse_id=horse_id,
                horse_name=h_name,
                amount_bet=amount_bet,
                payout=payout,
                displayed_payout=dp,
            )
        )

        # Update bet row with payout
        await pool.execute(
            "UPDATE bets SET payout = $1 WHERE id = $2",
            payout,
            bet_id,
        )

        # Credit winnings to player (if any)
        if payout > 0:
            async with pool.acquire() as conn, conn.transaction():
                # Lock accounts in sorted order
                house_row = await conn.fetchrow(
                    "SELECT balance FROM currency_accounts"
                    " WHERE user_id = $1 FOR UPDATE",
                    HOUSE_ACCOUNT_ID,
                )
                player_row = await conn.fetchrow(
                    "SELECT balance FROM currency_accounts"
                    " WHERE user_id = $1 FOR UPDATE",
                    user_id,
                )

                if house_row is None or player_row is None:
                    continue

                memo = f"Race #{race_id} payout: {h_name} won!"
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
                    -payout,
                    user_id,
                    payout,
                )

                new_player_balance = player_row["balance"] + payout
                await conn.execute(
                    "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                    house_row["balance"] - payout,
                    HOUSE_ACCOUNT_ID,
                )
                await conn.execute(
                    "UPDATE currency_accounts SET balance = $1 WHERE user_id = $2",
                    new_player_balance,
                    user_id,
                )

            # Emit event outside transaction
            balance_events.append(
                BalanceChangedEvent(
                    user_id=user_id,
                    new_balance=new_player_balance,
                    delta=payout,
                    memo=memo,
                )
            )

    return payouts, balance_events


async def get_bet_count(pool: asyncpg.Pool, race_id: int) -> int:
    """Get the number of bets placed on a race."""
    count: int = await pool.fetchval(
        "SELECT COUNT(*) FROM bets WHERE race_id = $1", race_id
    )
    return count


def format_payout_message(payouts: list[PayoutRecord]) -> str:
    """Format betting results for posting to the race thread."""
    if not payouts:
        return ""

    winners = [p for p in payouts if p.payout > 0]
    losers = [p for p in payouts if p.payout == 0]

    lines: list[str] = ["### Betting Results\n"]

    if winners:
        lines.append("Winners:")
        for p in winners:
            lines.append(
                f"💹 <@{p.user_id}> bet ¥{p.amount_bet:,} on "
                f"**{p.horse_name}** and won **¥{p.payout:,}**!"
            )

    if losers:
        lines.append("Losers:")
        for p in losers:
            lines.append(
                f"🔻 <@{p.user_id}> bet ¥{p.amount_bet:,} on "
                f"**{p.horse_name}** and lost."
            )

    return "\n".join(lines)
