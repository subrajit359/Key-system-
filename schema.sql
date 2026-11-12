CREATE TABLE IF NOT EXISTS licenses (
    id BIGSERIAL PRIMARY KEY,
    key_hash CHAR(64) UNIQUE NOT NULL,
    key_hint VARCHAR(12) NOT NULL,
    device_id VARCHAR(256),
    is_banned BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    note TEXT
);
