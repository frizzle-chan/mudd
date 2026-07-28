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
(`racing.py:597: bot: MuddBot`) and needs no ignore — so the fix is to make
`Movement` and `Speech` consistent with the cog that already got it right:

```python
def __init__(self, bot: MuddBot, ...) -> None:
    self.bot = bot
...
if member.guild.id != self.bot.guild_id:
```

**Bonus:** this also deletes the three `cast(discord.Client, self.bot)` calls
in `movement.py` (lines 204, 262, 298). `MuddBot <: commands.Bot <: discord.Client`, so once the
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
`_pool=cast(asyncpg.Pool, None)`. That is the correct trade: one explicit
cast in test scaffolding, where the object genuinely has no database,
instead of a false type on a production dataclass that misleads every call
site.

The source-level precedent for a required `_pool` is `Room`
(`room.py:47`), which already declares the field with no default. Its *test*
double, however, writes `_pool=None,  # ty: ignore[invalid-argument-type]`
(`entity_autocomplete_unit_test.py:60`), as does
`observers/skills_unit_test.py:23`. Rather than leave two styles for the
same problem — one of them ten lines from the other in the same file — both
have been normalized to the `cast` form, removing 2 further ignores. This
is a follow-through on the source fix, not an audit of test code.

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
class _RaceMessagePayload:
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
`payload: _RaceMessagePayload` instead of `kwargs: dict[str, object]` and
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

Because those two `get_entities` implementations now override a base-class
method, CLAUDE.md's `@override` rule applies to them and both have been
annotated accordingly.

**Why `abc.ABC` and not a Protocol in `interfaces.py`.** CLAUDE.md
prescribes protocols there specifically for breaking import cycles, and this
mixin isn't a cycle problem — it *provides* a default implementation, which
Protocol inheritance handles awkwardly. `mudd/commands.py` already
establishes the ABC-for-behavior-contract precedent in this codebase.

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
- `uv run ruff check .`, `ruff format --check .`, `uv run vulture` — pass.
- `just` (the full gate: lint, format, types, entities, horses, verbs,
  squawk, vulture) — passes end to end.
- `just test` — **422 passed, 0 failed**, integration suite included.

An earlier draft of this report recorded 12 image-regression failures and
44 integration errors, and reasoned about them as environmental. That was
the right diagnosis but an incomplete fix, so both gaps have since been
closed rather than argued around:

- The 12 `*_image_test.py` failures were caused by a missing UnifontEX font.
  `mudd/rendering/chrome.py:24` falls back to `ImageFont.load_default()`
  when `/usr/share/fonts/truetype/unifontex/unifontex.ttf` is absent, so
  every rendered baseline diffed. The Dockerfile installs that font;
  the environment simply lacked it. Installing it turns all 12 green — the
  checked-in baselines were correct all along.
- The 44 integration errors were `socket.gaierror` from no PostgreSQL at
  host `db`. With a local server and the `mudd:mudd@db:5432/mudd`
  role/database that `tests/conftest.py` expects, the whole suite runs.

This matters for the audit's conclusions: Fix #2 is the one change with any
runtime surface, and it is now covered by the integration tests rather than
by unit tests alone plus a caveat.

Net: **10 source ignores removed, 3 redundant `cast()` calls removed, 2
unused imports removed (`typing.cast`, `functools`), 0 ignores added to
source.** On the test side, the two files forced to supply a pool gain an
explicit `cast(asyncpg.Pool, None)`, and the 2 pre-existing
`_pool=None  # ty: ignore` sites were normalized to the same form — so 12
ignores are gone repo-wide and no `_pool=None` remains.

## Production risk

CLAUDE.md flags this as a live service, so to state it plainly rather than
leave it implied: **the deployment risk here is near-zero.**

- No schema change, so no migration and nothing to roll back in the database.
- No slash-command or argument change, so no user-facing API surface moves.
- Fixes #1, #3, #4 and #5 are runtime-equivalent — annotations, a dataclass
  wrapper around calls that already happened, an abstract declaration both
  subclasses already satisfy, and one metadata assignment nothing reads.
- Fix #2 has the only runtime delta, and it is strictly safer: constructing
  `EntityInstance` or `Scene` without `_pool` now raises `TypeError` at
  construction instead of deferring an `AttributeError` to first database
  use. No such construction site exists in production code.

Rollback is a plain revert of the commit. The integration suite now runs
here and is green, so the pre-merge caveat an earlier draft carried is
discharged.

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
