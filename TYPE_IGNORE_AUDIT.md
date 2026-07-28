# Type-ignore audit (source code)

Scope: every `ty: ignore` / `type: ignore` in non-test source. Test files
(`*_unit_test.py`) are out of scope per the request, but where a source fix
forces a test change, that consequence is noted.

**Inventory: 10 ignores across 7 source files, in 5 distinct root causes.**
All 10 have a structural fix. Each fix below was applied and verified —
`ruff check`, `ruff format --check`, and `ty check` all pass with zero
remaining ignores in source.

| # | Site(s) | Rule | Root cause |
|---|---------|------|------------|
| 1 | `mudd/cogs/movement.py:199,250,292`, `mudd/cogs/speech.py:51` | `invalid-assignment` | Attribute annotated too wide, re-narrowed by assignment |
| 2 | `mudd/models/entity.py:211`, `mudd/scene.py:35` | `invalid-assignment` | `default=None` on a non-optional field to satisfy field ordering |
| 3 | `mudd/cogs/racing.py:1074,1117` | `no-matching-overload` | `dict[str, object]` splatted into an overloaded API |
| 4 | `mudd/models/room.py:28` | `unresolved-attribute` | Mixin calls a method it never declares |
| 5 | `mudd/utils/async_cached_property.py:35` | `invalid-argument-type` | `functools.update_wrapper` applied to a non-callable descriptor |

---

## 1. `bot: MuddBot = self.bot` — 4 ignores

```python
# movement.py:199, 250, 292 and speech.py:51
bot: MuddBot = self.bot  # ty: ignore[invalid-assignment]
if member.guild.id != bot.guild_id:
```

**Why the checker is right.** `Movement.__init__` declares
`bot: commands.Bot | None`, so `self.bot` really is `commands.Bot | None` —
a type that has no `guild_id`. The local re-annotation is a downcast *and* a
silent `None`-strip. The ignore was suppressing a genuine unsoundness: if
`self.bot` were ever `None`, `bot.guild_id` raises `AttributeError` at
runtime, and the annotation claims that can't happen.

**Structural fix: annotate the attribute at its true type.** These cogs are
only ever constructed with the real bot (`main.py:80,84`), and they read
`MuddBot`-specific state (`guild_id`). `Racing` already does this correctly
(`racing.py:598: bot: MuddBot`) and needs no ignore — so the fix is to make
`Movement` and `Speech` consistent with the cog that already got it right:

```python
def __init__(self, bot: MuddBot, ...) -> None:
    self.bot = bot
...
if member.guild.id != self.bot.guild_id:
```

**Bonus:** this also deletes four `cast(discord.Client, self.bot)` calls in
`movement.py`. `MuddBot <: commands.Bot <: discord.Client`, so once the
attribute is typed honestly the casts are redundant. The `| None` on the
parameter was vestigial — no test or caller passes `None`.

## 2. `_pool: asyncpg.Pool = field(default=None)` — 2 ignores

```python
# entity.py:211 and scene.py:35
_pool: asyncpg.Pool = field(repr=False, compare=False, default=None)  # ty: ignore[invalid-assignment]
```

**Why the checker is right.** The field is declared non-optional and
defaulted to `None`. Every reader of `self._pool` — every `fetch`, every
`execute` — is typed against a guarantee the dataclass does not honor.

**Two causes are tangled here.** In `EntityInstance` the default is
*mechanically required*: `container_entity_id: str | None = None` precedes
`_pool`, and a non-default field cannot follow a defaulted one. In `Scene`
it isn't required at all — `user` and `room` precede it with no defaults —
so the `None` there is pure test convenience.

**Structural fix: `kw_only=True` instead of a false default.** A `kw_only`
field is exempt from positional ordering rules, so the ordering constraint
disappears and the field can be genuinely required:

```python
_pool: asyncpg.Pool = field(repr=False, compare=False, kw_only=True)
```

Zero production impact — all four internal construction sites
(`entity.py:298,691`, `scene.py:128`) already pass `_pool=` by keyword, and
`replace()` preserves it. This also matches `Room`, which already declares
`_pool: asyncpg.Pool = field(repr=False, compare=False)` with no default.

**Test consequence (out of scope but real).** Two unit tests construct these
objects without a pool and now must supply one:
`mudd/caches/entity_autocomplete_unit_test.py:43` and
`mudd/cogs/shop_unit_test.py:129`. The honest way to write that is
`_pool=cast(asyncpg.Pool, None)` — the same pattern `Room`'s test already
uses. That is the correct trade: one explicit cast in test scaffolding,
where the object genuinely has no database, instead of a false type on a
production dataclass that misleads every call site.

## 3. `channel.send(**kwargs)` — 2 ignores

```python
kwargs: dict[str, object] = {"content": msg.content}
if msg.image_data and msg.image_name:
    kwargs["file"] = discord.File(BytesIO(msg.image_data), filename=msg.image_name)
...
sent = await channel.send(**kwargs)  # ty: ignore[no-matching-overload]
```

**Why the checker is right.** `dict[str, object]` erases both the keys and
the value types. `discord.abc.Messageable.send` is heavily overloaded
(`file` vs `files` are mutually exclusive), and no overload accepts
arbitrary `object` values. The existing comment ("only include file if
present so the type checker sees a matching overload") describes an intent
the `dict[str, object]` type immediately discards.

**Structural fix: a typed payload with a single send path.** Replace the
bag-of-kwargs with a frozen dataclass and move the overload selection into
one place, where it is an explicit branch rather than a runtime dict shape:

```python
@dataclass(frozen=True, slots=True)
class RaceMessagePayload:
    """Content (and optional image) for a queued race message.

    `discord.File` is single-use — a payload must not be sent twice.
    """

    content: str | None
    file: discord.File | None

    async def send_to(self, dest: discord.abc.Messageable) -> discord.Message:
        """Send this payload, picking the matching `send()` overload."""
        if self.file is not None:
            return await dest.send(content=self.content, file=self.file)
        return await dest.send(content=self.content)
```

Both `_post_announcement` and `_post_to_thread` take
`payload: RaceMessagePayload` instead of `kwargs: dict[str, object]` and
call `await payload.send_to(...)`. `content` is `str | None` because
`PendingMessage.content` is (`racing/persistence.py:74`); typing it that way
keeps the payload faithful to its source rather than asserting non-null.

This is also the fix that removes a real hazard: `dict[str, object]` would
have accepted a typo'd key or a wrong-typed value silently.

## 4. `_DefaultVisibleEntities` mixin — 1 ignore

```python
class _DefaultVisibleEntities:
    """Mixin: get_visible_entities defaults to get_entities."""

    async def get_visible_entities(self) -> list[EntityInstance]:
        return await self.get_entities()  # ty: ignore[unresolved-attribute]
```

**Why the checker is right.** The mixin has a hard requirement on its
subclasses — they must provide `get_entities` — and expresses it only in a
docstring. Nothing stops a new subclass from omitting the method; the
failure surfaces at runtime, and the ignore guarantees the checker won't
warn.

**Structural fix: make the mixin declare its own contract.**

```python
class _DefaultVisibleEntities(abc.ABC):
    """Mixin: get_visible_entities defaults to get_entities."""

    @abc.abstractmethod
    async def get_entities(self) -> list[EntityInstance]:
        """Get all entity instances in this context."""

    async def get_visible_entities(self) -> list[EntityInstance]:
        return await self.get_entities()
```

Both current subclasses (`EntityModal:432`, `InventoryThread:473`) already
implement `get_entities`, so nothing changes for them. `abc.ABC` composes
fine with `@dataclass(frozen=True)`. The requirement is now enforced at
class-definition time instead of documented and hoped for, which is exactly
the guarantee the `IRoom` protocol in `models/interfaces.py:90` already
states for the same pair of methods.

## 5. `functools.update_wrapper(self, func)` — 1 ignore

```python
functools.update_wrapper(self, func)  # ty: ignore[invalid-argument-type]
```

**Why the checker is right.** `update_wrapper` is typed for wrapper
*functions* — it expects a callable and returns it. `async_cached_property`
is a descriptor, not a callable, so it does not satisfy the parameter type.
It is also mostly wrong at runtime here: `update_wrapper` sets `__wrapped__`,
`__module__`, `__qualname__`, `__name__`, and copies `func.__dict__`, none of
which a descriptor uses. `__name__` in particular is dead — the class already
tracks the name in `self._name` (line 34), and `__set_name__` (line 37)
overwrites it with the authoritative attribute name.

**Structural fix: copy the one attribute that actually matters.**

```python
self.__doc__ = func.__doc__
```

`__doc__` is the only piece of metadata a descriptor surfaces (via `help()`
and introspection on the class attribute). This drops the `functools`
import entirely.

---

## Verification

Applied all five fixes together on `claude/typeignore-audit-1uevgq`:

- `uv run ty check` — **All checks passed** (baseline was also clean; the
  fixes hold with zero ignores rather than by suppression).
- `uv run ruff check .` and `ruff format --check .` — pass.
- `uv run pytest mudd/` — 366 passed, 12 failed. All 12 are image-regression
  tests (`*_image_test.py`); confirmed pre-existing by stashing the diff and
  re-running — identical 12 failures. They are font-rendering diffs in this
  container, unrelated to these changes.
- Integration tests (`tests/integration/`) could not run here — no
  PostgreSQL reachable (`socket.gaierror`). Fix #2 is the one with any
  runtime surface (dataclass field ordering), and it is exercised by the
  unit tests that construct `EntityInstance`; a local `just test` run
  against the dev database is worth doing before merge.

Net: **10 ignores removed, 4 redundant `cast()` calls removed, 1 unused
import removed, 0 ignores added to source.** Two test files gain an explicit
`cast(asyncpg.Pool, None)`, matching the pattern `Room`'s test already uses.

## Related suppressions (not type ignores)

Three `# noqa` comments exist and are all legitimate — they document
intentional style choices rather than hide type errors, and need no change:

- `mudd/models/__init__.py:25` and `mudd/events/__init__.py:45` —
  `RUF022`, `__all__` grouped by category instead of sorted.
- `scripts/optimize_images.py:174` — `BLE001`, deliberate broad catch to
  keep a batch running.

`.claude/skills/skill-creator/scripts/quick_validate.py:14` carries a
`type: ignore[import-untyped]`, but that path is vendored and already
excluded from both `[tool.ty.src]` and `[tool.ruff]` in `pyproject.toml`.
