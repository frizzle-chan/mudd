"""Unit tests for ViewSkill and ViewEntity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from mudd.models.entity import ResolvedEntity
from mudd.skills.registry import Skill
from mudd.utils.text import Rarity
from mudd.views import ViewEntity, ViewSkill


@dataclass(frozen=True)
class _StubEntity:
    """Minimal IReadableEntity stub for ViewEntity tests."""

    entity: ResolvedEntity
    instance_id: UUID | str = "stub-instance"
    room_id: str | None = "room-1"
    owner_id: int | None = None
    id: str = "stub"
    name: str = "Stub"
    description_short: str | None = None
    description_long: str | None = None
    contents_visible: bool = True
    rarity: Rarity = "none"
    is_focusable: bool = True
    can_pickup: bool = True
    can_drop: bool = True
    can_destroy: bool = True

    async def get_contents(self) -> list:
        return []

    def with_observers(self, *observers: object) -> _StubEntity:
        return self


def _make_resolved(
    *,
    on_use: str | None = None,
    on_open: str | None = None,
    contents_visible: bool = True,
    rarity: Rarity = "none",
    name: str = "Test Entity",
) -> ResolvedEntity:
    return ResolvedEntity(
        id="test",
        name=name,
        description_short=None,
        description_long=None,
        on_look=None,
        on_touch=None,
        on_attack=None,
        on_use=on_use,
        on_take=None,
        on_open=on_open,
        on_close=None,
        on_drop=None,
        on_fish=None,
        contents_visible=contents_visible,
        rarity=rarity,
    )


def _make_view(
    *,
    on_use: str | None = None,
    on_open: str | None = None,
    contents_visible: bool = True,
    rarity: Rarity = "none",
    name: str = "Test Entity",
) -> ViewEntity:
    resolved = _make_resolved(
        on_use=on_use,
        on_open=on_open,
        contents_visible=contents_visible,
        rarity=rarity,
        name=name,
    )
    stub = _StubEntity(entity=resolved, name=name, rarity=rarity)
    return ViewEntity(stub)


class TestViewEntity:
    def test_shop_emoji_for_shop_entity(self) -> None:
        view = _make_view(name="Shopkeeper", on_use='{{ effects.shop("general") }}')
        assert view.display_name == "🏪 Shopkeeper"

    def test_shop_emoji_in_bold_name(self) -> None:
        view = _make_view(name="Fishmonger", on_use='{{ effects.shop("fish") }}')
        assert view.name == "**🏪 Fishmonger**"

    def test_no_shop_emoji_for_plain_entity(self) -> None:
        view = _make_view(name="Rock")
        assert view.display_name == "Rock"

    def test_no_shop_emoji_when_on_use_has_no_shop(self) -> None:
        view = _make_view(name="Lever", on_use="{{ effects.broadcast('click') }}")
        assert view.display_name == "Lever"

    def test_searchable_takes_precedence_over_shop(self) -> None:
        """An entity that is both searchable and a shop shows 🔍, not 🏪."""
        view = _make_view(
            name="Magic Chest",
            on_open="{{ effects.set_focus() }}",
            on_use='{{ effects.shop("magic") }}',
            contents_visible=False,
        )
        assert view.display_name == "🔍 Magic Chest"

    def test_rarity_emoji_with_shop(self) -> None:
        view = _make_view(
            name="Rare Merchant",
            on_use='{{ effects.shop("rare") }}',
            rarity="rare",
        )
        assert view.display_name == "🏪 Rare Merchant 🔵"


class TestViewSkill:
    def test_name_bold_with_emoji(self) -> None:
        view = ViewSkill(Skill.AGILITY)
        assert view.name == "**⚡ Agility**"

    def test_display_name_emoji_no_bold(self) -> None:
        view = ViewSkill(Skill.AGILITY)
        assert view.display_name == "⚡ Agility"

    def test_str_returns_name(self) -> None:
        view = ViewSkill(Skill.AGILITY)
        assert str(view) == view.name

    def test_all_skills_have_emoji(self) -> None:
        for skill in Skill:
            view = ViewSkill(skill)
            assert view.display_name != skill.display_name

    def test_attack_emoji(self) -> None:
        assert ViewSkill(Skill.ATTACK).name == "**⚔️ Attack**"

    def test_speech_emoji(self) -> None:
        assert ViewSkill(Skill.SPEECH).name == "**💬 Speech**"

    def test_vitality_emoji(self) -> None:
        assert ViewSkill(Skill.VITALITY).name == "**❤️ Vitality**"

    def test_fishing_emoji(self) -> None:
        assert ViewSkill(Skill.FISHING).name == "**🎣 Fishing**"
