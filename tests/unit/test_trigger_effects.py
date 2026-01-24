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
