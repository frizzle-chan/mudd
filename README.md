# MUDD: Multi User Dungeon (Discord)

[![codecov](https://codecov.io/github/frizzle-chan/mudd/graph/badge.svg?token=JM8BYHR8I4)](https://codecov.io/github/frizzle-chan/mudd)

A Discord-native Multi User Dungeon. It's a text-based multiplayer RPG inside a Discord server!

- Rooms in the world are mapped to Discord channels. You can only see and post in the channel that corresponds with your in-world location.
- Players explore and interact using slash commands with context-aware autocomplete.
- The world is filled with inspectable, lootable, and sometimes destructible items and characters. Your interactions impact the shared world with other players.
- Player inventories are managed as private [forum channels](https://support.discord.com/hc/en-us/articles/6208479917079-Forum-Channels-FAQ). Each item gets its own item management thread.
- Worlds are authored in user-friendly [recfiles](https://www.gnu.org/software/recutils/) in [data/worlds](./data/worlds/), are synced to a Postgres datbase, and the bot continually reconciles Discord state with the database state.

## How to play

- **/look** around
- **/interact** with things you find
- **/move** between rooms

### Items and inventory
Items are marked with icons showing how rare they are:
- ⚪ Common
- 🟢 Uncommon
- 🔵 Rare
- 🟣 Epic
- 🟠 Legendary
- ㊙️ Mythic

Quest 🔷 items are placed deliberately or granted as rewards.

Tip: By default, slash commands will autocomplete items present in the room you are in. If you want to reference items in your inventory, use the `i.` prefix, e.g., `/interact with:i.Gadget action:drop`.

### Money 💴
The wallet in your inventory shows your current bank balance.

- **/pay** other players in the same room as you to transfer funds.

## Codebase tour
