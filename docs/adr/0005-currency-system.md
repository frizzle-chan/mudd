# ADR 0005: Currency System

## Status

Accepted

## Context

MUDD needs an in-game economy to enable player-to-player transactions, purchases from NPCs (future), and reward systems. The economy should feel integrated into the existing item and inventory systems rather than bolted on.

Key requirements:
- **Currency type**: A thematic currency fitting the game world
- **Balance visibility**: Players should see their balance through the inventory system
- **Transactions**: Players need to transfer currency to each other
- **Auditability**: Transaction history for debugging and player disputes
- **Integrity**: Prevent negative balances and ensure atomic transfers

## Decisions

### Currency Choice

In the context of **choosing an in-game currency**, facing **the need for a currency that fits the game's aesthetic and is easy to display**, we decided to **use Yen (¥)**, to achieve **a clean, recognizable symbol that works well with integer amounts**, accepting **that this is a stylistic choice without gameplay implications**.

**Starting Balance:** ¥1000 for all new players.

### Wallet as Inventory Item

In the context of **displaying player balance**, facing **the tension between adding new UI elements vs. using existing systems**, we decided to **represent the wallet as an entity in the player's inventory**, to achieve **balance visibility via the existing look command without new slash commands**, accepting **that wallet threads will need special handling to prevent dropping**.

**Wallet Behavior:**
- Wallet entity with non-spawnable rarity (not available via spawning pools)
- Cannot be dropped (drop handler shows error message without actually dropping)
- Look handler displays current balance by injecting balance into the template
- Wallet appears as a thread in the player's inventory forum

### Double-Entry Ledger

In the context of **tracking currency transactions**, facing **the need for auditability and integrity**, we decided to **implement a double-entry ledger with separate transaction and ledger tables**, to achieve **complete audit trail and self-balancing books**, accepting **additional database complexity over a simple balance column**.

**Schema Design:**
- **Accounts table**: Per-user balance with wallet instance link
- **Transactions table**: Transaction metadata (memo, idempotency key, timestamp)
- **Ledger table**: Individual entries (account, amount, transaction reference)

**House Account:** A special "house" account with large balance for system-initiated grants and future NPC purchases.

### Transfer Implementation

In the context of **executing currency transfers**, facing **the need for atomic operations that prevent race conditions and negative balances**, we decided to **lock accounts in sorted order and validate/update within a single transaction**, to achieve **deadlock-free atomic transfers**, accepting **brief lock contention during transfers**.

**Transfer Logic:**
1. Validate amount is positive
2. Lock both accounts in deterministic order (prevents deadlocks)
3. Check sender balance is sufficient
4. Insert transaction record (with optional idempotency key)
5. Insert ledger entries (debit sender, credit recipient)
6. Update both account balances
7. All in single database transaction

### Wallet Bootstrap via Sync

In the context of **creating wallets for players**, facing **the need to ensure every player has a wallet and currency account**, we decided to **bootstrap wallets during the periodic sync alongside inventory forum creation**, to achieve **automatic wallet provisioning without requiring player action**, accepting **additional sync complexity**.

**Bootstrap Process:**
1. During user forum sync, check if user has a wallet instance
2. If missing, create wallet entity instance in inventory
3. Create inventory thread for the wallet
4. Create currency account with starting balance
5. Link wallet instance in the account

### /pay Command

In the context of **enabling player-to-player transfers**, facing **the need for a simple, discoverable interface**, we decided to **implement a `/pay` slash command**, to achieve **intuitive currency transfer with Discord's native UI**, accepting **an additional command to maintain**.

**Validation Rules:**
- Amount must be positive integer
- Cannot pay yourself
- Both players must be in the same room
- Both players must have wallets/accounts
- Sender must have sufficient balance

**Post-Transfer Updates:**
- Edit both wallet thread descriptions with new balance
- Post transaction notification to both wallet threads

## Consequences

### Positive

- Balance visibility through existing look system - no new UI patterns
- Double-entry ledger provides complete audit trail
- Atomic transfers prevent race conditions and negative balances
- Idempotency keys enable safe retry of failed operations
- House account enables future NPC purchases and system grants
- Wallet as inventory item feels integrated, not bolted on

### Negative

- Additional database tables and sync complexity
- Wallet thread requires special handling in inventory service
- Balance injection into templates requires template context extension
- Players cannot "hide" their wallet (always visible in inventory)

### Future Considerations

- NPC vendors that accept currency
- Item pricing and purchase commands
- Currency sinks (taxes, fees, gambling)
- Interest on house account loans
- Transaction history query command
- Currency conversion between types
