"""Unit tests for EffectsObserver event collection."""

import pytest

from mudd.events import (
    BroadcastEvent,
    DestroySignal,
    DispenseSignal,
    DropSignal,
    EffectsCollector,
    GrantCurrencyEvent,
    GrantEvent,
    GrantRandomEvent,
    PickupSignal,
)
from mudd.observers import EffectsObserver


class TestEffectsObserverNotify:
    """Tests for EffectsObserver.notify() event collection."""

    def test_broadcast_event_collected(self):
        """BroadcastEvent is collected in broadcasts list."""
        observer = EffectsObserver()
        observer.notify(BroadcastEvent(message="Hello world"))
        assert observer.broadcasts == ["Hello world"]

    def test_multiple_broadcasts_collected(self):
        """Multiple broadcast events are collected in order."""
        observer = EffectsObserver()
        observer.notify(BroadcastEvent(message="First"))
        observer.notify(BroadcastEvent(message="Second"))
        assert observer.broadcasts == ["First", "Second"]

    def test_grant_event_collected(self):
        """GrantEvent is collected in grants list."""
        observer = EffectsObserver()
        observer.notify(GrantEvent(entity_id="golden_key"))
        assert observer.grants == ["golden_key"]

    def test_grant_random_event_collected(self):
        """GrantRandomEvent is collected in grant_randoms list."""
        observer = EffectsObserver()
        observer.notify(GrantRandomEvent(tag="loot"))
        assert observer.grant_randoms == ["loot"]

    def test_grant_currency_event_collected(self):
        """GrantCurrencyEvent is collected in currency_grants list."""
        observer = EffectsObserver()
        observer.notify(GrantCurrencyEvent(amount=100))
        assert observer.currency_grants == [100]

    def test_pickup_signal_sets_flag(self):
        """PickupSignal sets has_pickup flag."""
        observer = EffectsObserver()
        assert observer.has_pickup is False
        observer.notify(PickupSignal())
        assert observer.has_pickup is True

    def test_drop_signal_sets_flag(self):
        """DropSignal sets has_drop flag."""
        observer = EffectsObserver()
        assert observer.has_drop is False
        observer.notify(DropSignal())
        assert observer.has_drop is True

    def test_destroy_signal_sets_flag(self):
        """DestroySignal sets has_destroy flag."""
        observer = EffectsObserver()
        assert observer.has_destroy is False
        observer.notify(DestroySignal())
        assert observer.has_destroy is True

    def test_dispense_signal_sets_flag(self):
        """DispenseSignal sets has_dispense flag."""
        observer = EffectsObserver()
        assert observer.has_dispense is False
        observer.notify(DispenseSignal())
        assert observer.has_dispense is True


class TestEffectsCollector:
    """Tests for EffectsCollector template API."""

    def test_broadcast_returns_empty_string(self):
        """broadcast() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.broadcast("Hello")
        assert result == ""
        assert observer.broadcasts == ["Hello"]

    def test_broadcast_ignores_empty_message(self):
        """broadcast() ignores empty messages."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        collector.broadcast("")
        assert observer.broadcasts == []

    def test_pickup_returns_empty_string(self):
        """pickup() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.pickup()
        assert result == ""
        assert observer.has_pickup is True

    def test_drop_returns_empty_string(self):
        """drop() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.drop()
        assert result == ""
        assert observer.has_drop is True

    def test_destroy_returns_empty_string(self):
        """destroy() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.destroy()
        assert result == ""
        assert observer.has_destroy is True

    def test_grant_returns_empty_string(self):
        """grant() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.grant("golden_key")
        assert result == ""
        assert observer.grants == ["golden_key"]

    def test_grant_ignores_empty_entity_id(self):
        """grant() ignores empty entity IDs."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        collector.grant("")
        assert observer.grants == []

    def test_grant_random_returns_empty_string(self):
        """grant_random() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.grant_random("loot")
        assert result == ""
        assert observer.grant_randoms == ["loot"]

    def test_grant_random_ignores_empty_tag(self):
        """grant_random() ignores empty tags."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        collector.grant_random("")
        assert observer.grant_randoms == []

    def test_grant_currency_returns_empty_string(self):
        """grant_currency() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.grant_currency(100)
        assert result == ""
        assert observer.currency_grants == [100]

    def test_grant_currency_ignores_zero_amount(self):
        """grant_currency() ignores zero amounts."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        collector.grant_currency(0)
        assert observer.currency_grants == []

    def test_grant_currency_ignores_negative_amount(self):
        """grant_currency() ignores negative amounts."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        collector.grant_currency(-50)
        assert observer.currency_grants == []

    def test_dispense_returns_empty_string(self):
        """dispense() returns empty string for inline template use."""
        observer = EffectsObserver()
        collector = EffectsCollector(observer)
        result = collector.dispense()
        assert result == ""
        assert observer.has_dispense is True


class TestEffectsObserverFlush:
    """Tests for EffectsObserver.flush()."""

    @pytest.mark.asyncio
    async def test_flush_is_noop(self):
        """flush() is a no-op (cog handles side effects)."""
        observer = EffectsObserver()
        observer.notify(BroadcastEvent(message="Hello"))
        observer.notify(PickupSignal())

        # flush() should not raise and should not clear state
        await observer.flush()

        # State should be preserved
        assert observer.broadcasts == ["Hello"]
        assert observer.has_pickup is True
