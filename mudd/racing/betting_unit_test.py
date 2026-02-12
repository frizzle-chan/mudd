"""Unit tests for betting module."""

from mudd.racing.betting import PayoutRecord, format_payout_message


def test_format_payout_message_empty() -> None:
    assert format_payout_message([]) == ""


def test_format_payout_message_winner_only() -> None:
    payouts = [
        PayoutRecord(
            user_id=123,
            horse_id="flash",
            horse_name="Flash",
            amount_bet=100,
            payout=350,
            displayed_payout=3.5,
        ),
    ]
    result = format_payout_message(payouts)
    assert "### Betting Results" in result
    assert "<@123>" in result
    assert "Flash" in result
    assert "¥100" in result
    assert "¥350" in result


def test_format_payout_message_loser_only() -> None:
    payouts = [
        PayoutRecord(
            user_id=456,
            horse_id="thunder",
            horse_name="Thunder",
            amount_bet=50,
            payout=0,
            displayed_payout=2.0,
        ),
    ]
    result = format_payout_message(payouts)
    assert "### Betting Results" in result
    assert "<@456>" in result
    assert "Thunder" in result


def test_format_payout_message_mixed() -> None:
    payouts = [
        PayoutRecord(
            user_id=123,
            horse_id="flash",
            horse_name="Flash",
            amount_bet=100,
            payout=350,
            displayed_payout=3.5,
        ),
        PayoutRecord(
            user_id=456,
            horse_id="thunder",
            horse_name="Thunder",
            amount_bet=200,
            payout=0,
            displayed_payout=2.0,
        ),
    ]
    result = format_payout_message(payouts)
    lines = result.split("\n")
    # Header (with trailing \n) + blank + Winners: + winner + Losers: + loser
    assert len(lines) == 6
    assert "Winners:" in lines[2]
    assert "won" in lines[3]
    assert "Losers:" in lines[4]
    assert "Thunder" in lines[5]


def test_format_payout_message_large_amounts() -> None:
    payouts = [
        PayoutRecord(
            user_id=789,
            horse_id="bolt",
            horse_name="Bolt",
            amount_bet=1000,
            payout=5500,
            displayed_payout=5.5,
        ),
    ]
    result = format_payout_message(payouts)
    assert "¥1,000" in result
    assert "¥5,500" in result
