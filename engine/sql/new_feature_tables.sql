-- Optional enhanced Fortress schema additions.
-- These are additive tables and do not alter existing tables.

CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE users IS 'Optional enhanced user management table for feature-flagged flows.';
COMMENT ON COLUMN users.username IS 'Unique login identifier.';
COMMENT ON COLUMN users.last_login IS 'Most recent successful login timestamp.';
COMMENT ON COLUMN users.is_active IS 'Whether the account can authenticate and transact.';

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active);

CREATE TABLE IF NOT EXISTS user_broker_connections (
    connection_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    broker_name TEXT NOT NULL CHECK (broker_name IN ('Zerodha', 'Dhan')),
    broker_client_id TEXT,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, broker_name)
);

COMMENT ON TABLE user_broker_connections IS 'Stores encrypted broker credentials per user.';
COMMENT ON COLUMN user_broker_connections.access_token_encrypted IS 'Fernet-encrypted access token.';

CREATE INDEX IF NOT EXISTS idx_user_broker_connections_user ON user_broker_connections (user_id);
CREATE INDEX IF NOT EXISTS idx_user_broker_connections_active ON user_broker_connections (is_active);

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK (order_type IN ('Buy', 'Sell')),
    quantity NUMERIC(18, 4) NOT NULL CHECK (quantity > 0),
    price NUMERIC(18, 4),
    status TEXT NOT NULL DEFAULT 'Pending',
    broker_name TEXT NOT NULL,
    broker_order_id TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE orders IS 'Tracks orders placed from Fortress when enhanced features are enabled.';

CREATE INDEX IF NOT EXISTS idx_orders_user_created_at ON orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_broker ON orders (broker_name);
