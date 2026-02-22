# ADR 0008: Merchant Shop System

## Status

Proposed

## Context

MUDD has a currency system (ADR 0005) but no way for players to spend or earn money through gameplay. Players need NPCs that buy and sell items, creating a functional economy where fishing, exploring, and collecting have monetary value. The system should encourage players to seek out the right merchant for the best price.

Key requirements:
- **Buy and sell items**: Players trade items with NPC-run shops for currency
- **Dynamic pricing**: Prices respond to supply and demand, not static values
- **Merchant specialization**: Merchants that deal in specific goods offer better prices
- **Threaded interaction**: Trading happens in Discord threads with dedicated commands
- **Multiple access points**: Different entities (NPCs, terminals, machines) can connect to the same shop

## Decisions

### Shops as Independent Concept

In the context of **connecting players to merchants**, facing **the desire for multiple entities to serve as storefronts for the same inventory**, we decided to **separate the shop (stock, pricing, preferences) from the entity (NPC, terminal, kiosk) that provides access to it**, to achieve **flexible shop access where a fishmonger NPC and a computer terminal can both connect to the same Fish Market**, accepting **an extra layer of indirection between entities and shops**.

**Shop definition:**
- Display name (used in thread titles and messages)
- Preferred tag (items matching this tag get preferential pricing)
- Sell spread (percentage of dynamic price merchants pay when buying from players)
- Restock configuration (tag to draw from, interval)

**Entity connection:**
- Entities connect to shops via a new `effects.shop()` template effect
- The entity's handler (on_trade, on_use, etc.) calls `effects.shop("shop-id")` to open a trading session
- The entity itself knows nothing about pricing or stock — it's just a doorway

### Thread-Based Trading UX

In the context of **providing a trading interface**, facing **the need for a contained, conversational trading experience**, we decided to **create a Discord thread for each trading session with dedicated /buy and /sell commands**, to achieve **a focused trading space that doesn't clutter the main room channel**, accepting **thread management overhead and cleanup responsibility**.

**Opening a trade:**
1. Player interacts with a merchant entity using talk/trade/shop verbs
2. Entity handler fires `effects.shop("shop-id")`
3. A broadcast message is sent to the room channel: "@frizzle begins talking to **Fishmonger**"
4. A thread is created on that message, named "{player} trading with {shop display name}"
5. The shop posts an overview message listing stocked items and prices
6. The player enters a trading state linked to this shop and thread

**During a trade:**
- `/buy` and `/sell` slash commands are only active when the player is in a trading state
- Each transaction posts a confirmation message to the thread
- The shop overview can be refreshed to reflect price changes from transactions

**Exiting a trade:**
- Moving to another room implicitly ends the trading session (same as focus clearing)
- Interacting with the merchant again starts a new session (old thread is archived)
- The thread is archived when the session ends

### /buy and /sell Commands

In the context of **executing trades**, facing **the need for discoverable, type-safe trade commands**, we decided to **implement /buy and /sell as slash commands with autocomplete that only activate in valid trading threads**, to achieve **a familiar command interface that guides players to available trades**, accepting **two new slash commands to maintain**.

**/buy behavior:**
- Autocomplete shows only in-stock items with their prices
- Only items the shop currently has in stock appear
- One item per transaction
- Currency is transferred from the player to the house account
- Item instance moves from shop stock to player inventory

**/sell behavior:**
- Autocomplete shows the player's tradeable inventory items (items with a rarity) with the price the shop will pay
- One item per transaction
- Currency is transferred from the house account to the player
- Item instance moves from player inventory to shop stock

### Dynamic Pricing

In the context of **setting item prices**, facing **the need for prices that respond to supply and demand rather than being static**, we decided to **calculate prices dynamically based on the shop's current stock of each item**, to achieve **an organic economy where flooding a shop with fish drives fish prices down**, accepting **price volatility and the need for a price floor**.

**Base price:**
- Each item's base price is derived from its rarity tier
- Rarity tiers map to base price ranges (using monetary bundles as benchmarks)

**Dynamic adjustment:**
- As a shop's stock of an item increases, the price decreases
- As stock decreases (through player purchases), the price increases
- This creates natural supply/demand curves per shop

**Price floor:**
- The buy price (what merchants pay players) never drops below 25% of the base price
- This prevents items from becoming completely worthless even when a shop is flooded

### Buy/Sell Spread

In the context of **merchant profit margins**, facing **the need to prevent infinite money exploits and create realistic trade economics**, we decided to **apply a configurable spread between buy and sell prices**, to achieve **a currency sink where merchants sell items for more than they buy them**, accepting **that players cannot profit by buying and immediately reselling to the same shop**.

**Spread behavior:**
- The sell price (what the merchant charges players) is the full dynamic price
- The buy price (what the merchant pays players) is the dynamic price multiplied by the spread percentage
- Default spread: 50% (merchant buys at half the sell price)
- Spread is configurable per shop

### Preferred Tag Bonus

In the context of **merchant specialization**, facing **the desire for players to seek out the right merchant for the best deal**, we decided to **give shops a preferred tag that provides a pricing bonus for matching items**, to achieve **meaningful merchant differentiation where the fishmonger pays more for fish than a general store**, accepting **that players must explore to discover which merchants specialize in what**.

**Bonus behavior:**
- All merchants buy any tradeable item
- Items matching the shop's preferred tag receive a multiplier on the buy price
- Preferred multiplier: 1.5x (stacks with the spread — so a 50% spread shop pays 75% of dynamic price for preferred items)
- This rewards players for traveling to the right merchant

### Daily Restocking

In the context of **populating shop inventories**, facing **the need for shops to have items available for purchase even before players sell to them**, we decided to **have shops spawn one weighted-random item from their preferred tag daily, similar to spawning pools**, to achieve **baseline shop inventory that grows organically alongside player-driven stock**, accepting **that shop stock can grow indefinitely**.

**Restock behavior:**
- Each shop spawns one item per day from entities matching its preferred tag
- Selection uses rarity-weighted random, same algorithm as spawning pools
- Stock has no upper cap — it grows indefinitely from restocks and player sells
- Items bought by players are removed from stock (not destroyed, transferred to inventory)

### House Account Integration

In the context of **merchant currency flow**, facing **the existing double-entry ledger and house account from ADR 0005**, we decided to **route all merchant transactions through the house account**, to achieve **consistent accounting using the established currency infrastructure**, accepting **that merchant profits/losses are absorbed by the house account**.

**Transaction flow:**
- Player buys: currency transfers from player account to house account
- Player sells: currency transfers from house account to player account
- Uses existing `transfer_currency()` with full audit trail

## Consequences

### Positive

- Players have meaningful ways to earn and spend currency through gameplay
- Dynamic pricing creates an organic economy that responds to player behavior
- Preferred tags encourage exploration and route planning (finding the right merchant)
- Thread-based UX keeps trading contained and conversational
- Shop/entity separation allows creative access points (NPCs, terminals, vending machines)
- Builds on existing systems: currency ledger, entity tags, rarity, spawning pool algorithm, effects pattern
- House account integration provides full audit trail for all trades

### Negative

- New tables required for shops and shop stock
- Thread lifecycle management adds Discord API surface area
- Dynamic pricing requires careful tuning to avoid degenerate cases
- Players may find price floors frustrating when trying to sell bulk items
- Two new slash commands to maintain with context-dependent autocomplete

### Future Considerations

- Buy/sell quantities (bulk trading)
- Shop-to-shop price arbitrage as intentional gameplay
- Time-limited sales or rotating stock
- Player-owned shops
- Trade history command
- Price charts or market data visibility
- Shop reputation or loyalty discounts
- Merchant dialogue and personality via thread messages
