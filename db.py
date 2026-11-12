import os
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Copy .env.example to .env and configure it.")

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=8,
    kwargs={"row_factory": dict_row},
    open=True,
)

def initialize():
    with pool.connection() as conn:
        conn.execute("""
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
        CREATE INDEX IF NOT EXISTS idx_licenses_created_at ON licenses(created_at);
        """)
        conn.commit()

def get_license(key_hash):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT * FROM licenses WHERE key_hash = %s", (key_hash,)
        ).fetchone()

def create_license(key_hash, hint, expires_at=None, note=None):
    with pool.connection() as conn:
        return conn.execute(
            """INSERT INTO licenses (key_hash, key_hint, expires_at, note)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (key_hash, hint, expires_at, note)
        ).fetchone()["id"]

def license_action(key_hash, action, value=None):
    queries = {
        "reset": "UPDATE licenses SET device_id=NULL, activated_at=NULL WHERE key_hash=%s",
        "ban": "UPDATE licenses SET is_banned=TRUE WHERE key_hash=%s",
        "unban": "UPDATE licenses SET is_banned=FALSE WHERE key_hash=%s",
        "delete": "DELETE FROM licenses WHERE key_hash=%s",
        "expiry": "UPDATE licenses SET expires_at=%s WHERE key_hash=%s",
    }
    with pool.connection() as conn:
        if action == "expiry":
            cur = conn.execute(queries[action], (value, key_hash))
        else:
            cur = conn.execute(queries[action], (key_hash,))
        conn.commit()
        return cur.rowcount > 0

def list_licenses(limit=20):
    with pool.connection() as conn:
        return conn.execute(
            """SELECT key_hint, device_id, is_banned, expires_at, created_at
               FROM licenses ORDER BY id DESC LIMIT %s""", (limit,)
        ).fetchall()

def stats():
    with pool.connection() as conn:
        return conn.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE device_id IS NOT NULL) AS activated,
                   COUNT(*) FILTER (WHERE is_banned) AS banned,
                   COUNT(*) FILTER (WHERE expires_at IS NOT NULL AND expires_at <= NOW()) AS expired
            FROM licenses
        """).fetchone()

def activate_or_verify(key_hash, device_id):
    # Lock the row so two devices cannot win the first-activation race.
    with pool.connection() as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT * FROM licenses WHERE key_hash=%s FOR UPDATE", (key_hash,)
            ).fetchone()
            if not row:
                return False, "invalid_key"
            if row["is_banned"]:
                return False, "banned"
            if row["expires_at"] is not None:
                expired = conn.execute(
                    "SELECT %s <= NOW() AS expired", (row["expires_at"],)
                ).fetchone()["expired"]
                if expired:
                    return False, "expired"
            if row["device_id"] is None:
                conn.execute(
                    """UPDATE licenses SET device_id=%s, activated_at=NOW()
                       WHERE key_hash=%s""", (device_id, key_hash)
                )
                return True, "activated"
            if row["device_id"] != device_id:
                return False, "device_mismatch"
            return True, "ok"
