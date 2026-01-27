-- Currency system tables for player economy
-- See ADR 0005 for design decisions

SET lock_timeout = '1s';
SET statement_timeout = '5s';

-- Currency accounts for players (user_id=0 is house account)
-- No FK constraint: house account (0) isn't a real user
CREATE TABLE currency_accounts (
    user_id BIGINT PRIMARY KEY,
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    wallet_instance_id UUID REFERENCES entity_instances(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- House account with 1 billion yen
INSERT INTO currency_accounts (user_id, balance)
VALUES (0, 1000000000);

-- Transaction log (double-entry ledger)
CREATE TABLE currency_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memo TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ledger entries (debit + credit per transaction)
CREATE TABLE currency_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES currency_transactions(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL REFERENCES currency_accounts(user_id) ON DELETE CASCADE,
    amount BIGINT NOT NULL,  -- positive = credit, negative = debit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_currency_ledger_account ON currency_ledger(account_id);
CREATE INDEX idx_currency_ledger_transaction ON currency_ledger(transaction_id);
