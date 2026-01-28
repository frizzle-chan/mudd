"""Tests for TriggerEffects side effect collection."""

from mudd.services.trigger_effects import TriggerEffects


class TestTriggerEffectsBroadcast:
    """Tests for TriggerEffects.broadcast() method."""

    def test_broadcast_collects_message(self):
        """broadcast() adds message to broadcasts list."""
        effects = TriggerEffects()
        effects.broadcast("Hello world")
        assert effects.broadcasts == ["Hello world"]

    def test_broadcast_collects_multiple_messages(self):
        """Multiple broadcast() calls collect all messages in order."""
        effects = TriggerEffects()
        effects.broadcast("First")
        effects.broadcast("Second")
        effects.broadcast("Third")
        assert effects.broadcasts == ["First", "Second", "Third"]

    def test_broadcast_returns_empty_string(self):
        """broadcast() returns empty string for inline template use."""
        effects = TriggerEffects()
        result = effects.broadcast("Test message")
        assert result == ""

    def test_broadcast_ignores_empty_string(self):
        """Empty string is not added to broadcasts."""
        effects = TriggerEffects()
        effects.broadcast("")
        assert effects.broadcasts == []

    def test_broadcast_ignores_none(self):
        """None is not added to broadcasts."""
        effects = TriggerEffects()
        effects.broadcast(None)  # type: ignore[arg-type]
        assert effects.broadcasts == []

    def test_broadcasts_empty_by_default(self):
        """New TriggerEffects has empty broadcasts list."""
        effects = TriggerEffects()
        assert effects.broadcasts == []


class TestTriggerEffectsDestroy:
    """Tests for TriggerEffects.destroy() method."""

    def test_destroy_sets_flag(self):
        """destroy() sets the has_destroy flag."""
        effects = TriggerEffects()
        effects.destroy()
        assert effects.has_destroy is True

    def test_destroy_returns_empty_string(self):
        """destroy() returns empty string for inline template use."""
        effects = TriggerEffects()
        result = effects.destroy()
        assert result == ""

    def test_has_destroy_false_by_default(self):
        """has_destroy is False before destroy() is called."""
        effects = TriggerEffects()
        assert effects.has_destroy is False


class TestTriggerEffectsMergeFrom:
    """Tests for TriggerEffects.merge_from() method."""

    def test_merge_broadcasts(self):
        """merge_from() combines broadcasts from both effects."""
        main = TriggerEffects()
        main.broadcast("Main message")

        other = TriggerEffects()
        other.broadcast("Other message")

        main.merge_from(other)

        assert main.broadcasts == ["Main message", "Other message"]

    def test_merge_currency_grants(self):
        """merge_from() combines currency grants from both effects."""
        main = TriggerEffects()
        main.grant_currency(100)

        other = TriggerEffects()
        other.grant_currency(200)

        main.merge_from(other)

        assert len(main.currency_grants) == 2
        assert main.currency_grants[0].amount == 100
        assert main.currency_grants[1].amount == 200

    def test_merge_destroy_flag(self):
        """merge_from() ORs destroy flag."""
        main = TriggerEffects()
        other = TriggerEffects()
        other.destroy()

        assert main.has_destroy is False
        main.merge_from(other)
        assert main.has_destroy is True

    def test_merge_does_not_copy_pickup_flag(self):
        """merge_from() does NOT merge pickup flag (caller handles it)."""
        main = TriggerEffects()
        other = TriggerEffects()
        other.pickup()

        main.merge_from(other)

        # pickup is NOT merged - it's handled separately by caller
        assert main.has_pickup is False
        assert other.has_pickup is True

    def test_merge_grants(self):
        """merge_from() combines grant effects."""
        main = TriggerEffects()
        main.grant("item_a")

        other = TriggerEffects()
        other.grant("item_b")

        main.merge_from(other)

        assert len(main.grants) == 2
        assert main.grants[0].entity_id == "item_a"
        assert main.grants[1].entity_id == "item_b"
