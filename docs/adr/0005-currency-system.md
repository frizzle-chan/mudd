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

In the context of **choosing an in-game currency**, facing **the need for a currency that fits the game's aesthetic and is easy to display**, we decided to **use Yen (\u00a5)**, to achieve **a clean, recognizable symbol that works well with integer amounts**, accepting **that this is a stylistic choice without gameplay implications**.

**Starting Balance:** \u00a51000 for all new players.

### Wallet as Inventory Item

In the context of **displaying player balance**, facing **the tension between adding new UI elements vs. using existing systems**, we decided to **represent the wallet as an entity in the player's inventory**, to achieve **balance visibility via the existing `/look` command without new slash commands**, accepting **that wallet threads will need special handling to prevent dropping**.

**Wallet Behavior:**
- Wallet entity with `Rarity: none` (not spawnable via pools)
- Cannot be dropped (`OnDrop` shows error message, no `effects.drop()`)
- `OnLook` displays current balance by injecting `{{ balance }}` into the template
- Wallet appears as a thread in the player's inventory forum

### Double-Entry Ledger

In the context of **tracking currency transactions**, facing **the need for auditability and integrity**, we decided to **implement a double-entry ledger with separate transaction and ledger tables**, to achieve **complete audit trail and self-balancing books**, accepting **additional database complexity over a simple balance column**.

**Schema Design:**
- `currency_accounts`: Per-user balance with wallet instance link
- `currency_transactions`: Transaction metadata (memo, idempotency key, timestamp)
- `currency_ledger`: Individual entries (account, amount, transaction reference)

**House Account:** User ID 0 is a special "house" account with \u00a51B balance for system-initiated grants and future NPC purchases.

### Transfer Implementation

In the context of **executing currency transfers**, facing **the need for atomic operations that prevent race conditions and negative balances**, we decided to **lock accounts in sorted user_id order and validate/update within a single transaction**, to achieve **deadlock-free atomic transfers**, accepting **brief lock contention during transfers**.

**Transfer Logic:**
1. Validate amount > 0
2. Lock both accounts in sorted user_id order (`FOR UPDATE`)
3. Check sender balance >= amount
4. Insert transaction record (with optional idempotency key)
5. Insert ledger entries (debit sender, credit recipient)
6. Update both account balances
7. All in single DB transaction

### Wallet Bootstrap via Sync

In the context of **creating wallets for players**, facing **the need to ensure every player has a wallet and currency account**, we decided to **bootstrap wallets during the periodic sync alongside inventory forum creation**, to achieve **automatic wallet provisioning without requiring player action**, accepting **additional sync complexity**.

**Bootstrap Process:**
1. During `sync_user_forums()`, check if user has a wallet instance
2. If missing, create wallet entity instance in inventory
3. Create inventory thread for the wallet
4. Create `currency_account` with \u00a51000 starting balance
5. Link `wallet_instance_id` in the account

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

## PostgreSQL Schema

```sql
-- Currency accounts for players (user_id=0 is house account)
CREATE TABLE currency_accounts (
    user_id BIGINT PRIMARY KEY,  -- No FK: house account (0) isn't a real user
    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    wallet_instance_id UUID REFERENCES entity_instances(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- House account with 1B
INSERT INTO currency_accounts (user_id, balance)
VALUES (0, 1000000000);

-- Transaction log (double-entry ledger)
CREATE TABLE currency_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memo TEXT,  -- e.g., "Payment from @alice", "Welcome bonus"
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ledger entries (debit + credit per transaction)
CREATE TABLE currency_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES currency_transactions(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL REFERENCES currency_accounts(user_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,  -- positive = credit, negative = debit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_currency_ledger_account ON currency_ledger(account_id);
CREATE INDEX idx_currency_ledger_transaction ON currency_ledger(transaction_id);
```

## Consequences

### Positive

- Balance visibility through existing `/look` system - no new UI patterns
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
