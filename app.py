import os
import secrets
import string
import hashlib
import logging
from datetime import datetime, timezone, timedelta

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("keysystem")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_SECRET = os.getenv("API_SECRET", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not API_SECRET:
    raise RuntimeError("API_SECRET is missing")

ADMIN_IDS = set()
for item in ADMIN_IDS_RAW.split(","):
    item = item.strip()
    if item.isdigit():
        ADMIN_IDS.add(int(item))

if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS is missing or invalid")

app = FastAPI(title="GUDU X BYPASS Keysystem", version="1.0.0")
telegram_app: Application | None = None


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                id BIGSERIAL PRIMARY KEY,
                license_key TEXT UNIQUE NOT NULL,
                device_id TEXT,
                device_hash TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                activated_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ NOT NULL,
                banned BOOLEAN NOT NULL DEFAULT FALSE,
                ban_reason TEXT,
                last_seen_at TIMESTAMPTZ,
                last_ip TEXT,
                total_checks INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_licenses_device_hash
            ON licenses(device_hash)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_licenses_expires_at
            ON licenses(expires_at)
        """)
        conn.commit()


def utcnow():
    return datetime.now(timezone.utc)


def normalize_device(device_id: str) -> str:
    return device_id.strip()[:512]


def device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def generate_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    parts = [
        "".join(secrets.choice(alphabet) for _ in range(5))
        for _ in range(4)
    ]
    return "GUDU-" + "-".join(parts)


def create_license(days: int):
    if days < 1 or days > 36500:
        raise ValueError("days must be between 1 and 36500")

    for _ in range(20):
        key = generate_key()
        try:
            with db() as conn:
                row = conn.execute(
                    """
                    INSERT INTO licenses (license_key, expires_at)
                    VALUES (%s, %s)
                    RETURNING license_key, expires_at
                    """,
                    (key, utcnow() + timedelta(days=days)),
                ).fetchone()
                conn.commit()
                return row
        except psycopg.errors.UniqueViolation:
            continue

    raise RuntimeError("Could not generate a unique license key")


def get_license(key: str):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM licenses WHERE license_key=%s",
            (key.strip().upper(),),
        ).fetchone()


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in ADMIN_IDS)


async def admin_only(update: Update) -> bool:
    if not is_admin(update):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ Admin only.")
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    await update.message.reply_text(
        "👑 GUDU X BYPASS Keysystem\n\n"
        "/gen <days> [count]\n"
        "/reset <key>\n"
        "/ban <key> [reason]\n"
        "/unban <key>\n"
        "/extend <key> <days>\n"
        "/delete <key>\n"
        "/info <key>\n"
        "/list\n"
        "/stats"
    )


async def cmd_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    try:
        days = int(context.args[0])
        count = int(context.args[1]) if len(context.args) > 1 else 1
        if count < 1 or count > 100:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /gen <days> [count]\nExample: /gen 30 5")
        return

    keys = []
    for _ in range(count):
        row = create_license(days)
        keys.append(f"{row['license_key']} — {row['expires_at'].date()}")

    await update.message.reply_text(
        f"✅ Generated {len(keys)} key(s):\n\n" + "\n".join(keys)
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /reset <key>")
        return

    key = context.args[0].strip().upper()
    with db() as conn:
        cur = conn.execute(
            """
            UPDATE licenses
            SET device_id=NULL, device_hash=NULL, activated_at=NULL,
                last_seen_at=NULL, last_ip=NULL
            WHERE license_key=%s
            """,
            (key,),
        )
        conn.commit()

    await update.message.reply_text(
        "✅ Device binding reset." if cur.rowcount else "❌ Key not found."
    )


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <key> [reason]")
        return

    key = context.args[0].strip().upper()
    reason = " ".join(context.args[1:]).strip() or "Banned by admin"

    with db() as conn:
        cur = conn.execute(
            "UPDATE licenses SET banned=TRUE, ban_reason=%s WHERE license_key=%s",
            (reason, key),
        )
        conn.commit()

    await update.message.reply_text(
        "🚫 Key banned." if cur.rowcount else "❌ Key not found."
    )


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <key>")
        return

    key = context.args[0].strip().upper()
    with db() as conn:
        cur = conn.execute(
            "UPDATE licenses SET banned=FALSE, ban_reason=NULL WHERE license_key=%s",
            (key,),
        )
        conn.commit()

    await update.message.reply_text(
        "✅ Key unbanned." if cur.rowcount else "❌ Key not found."
    )


async def cmd_extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    try:
        key = context.args[0].strip().upper()
        days = int(context.args[1])
        if days < 1 or days > 36500:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /extend <key> <days>")
        return

    with db() as conn:
        cur = conn.execute(
            """
            UPDATE licenses
            SET expires_at =
                CASE
                    WHEN expires_at > NOW()
                    THEN expires_at + (%s * INTERVAL '1 day')
                    ELSE NOW() + (%s * INTERVAL '1 day')
                END
            WHERE license_key=%s
            """,
            (days, days, key),
        )
        conn.commit()

    await update.message.reply_text(
        "✅ Expiry extended." if cur.rowcount else "❌ Key not found."
    )


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /delete <key>")
        return

    key = context.args[0].strip().upper()
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM licenses WHERE license_key=%s",
            (key,),
        )
        conn.commit()

    await update.message.reply_text(
        "🗑 Key deleted." if cur.rowcount else "❌ Key not found."
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /info <key>")
        return

    row = get_license(context.args[0].strip().upper())
    if not row:
        await update.message.reply_text("❌ Key not found.")
        return

    await update.message.reply_text(
        f"🔑 {row['license_key']}\n"
        f"📅 Expires: {row['expires_at']}\n"
        f"📱 Bound: {'Yes' if row['device_hash'] else 'No'}\n"
        f"🚫 Banned: {'Yes' if row['banned'] else 'No'}\n"
        f"🔎 Checks: {row['total_checks']}"
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    with db() as conn:
        rows = conn.execute(
            """
            SELECT license_key, expires_at, device_hash, banned
            FROM licenses
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()

    if not rows:
        await update.message.reply_text("No licenses.")
        return

    lines = []
    for r in rows:
        status = "BANNED" if r["banned"] else (
            "BOUND" if r["device_hash"] else "UNBOUND"
        )
        lines.append(
            f"{r['license_key']} | {status} | {r['expires_at'].date()}"
        )

    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE banned=TRUE) AS banned,
                COUNT(*) FILTER (WHERE device_hash IS NOT NULL) AS bound,
                COUNT(*) FILTER (WHERE expires_at > NOW() AND banned=FALSE) AS active,
                COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired
            FROM licenses
            """
        ).fetchone()

    await update.message.reply_text(
        "📊 Keysystem Stats\n\n"
        f"Total: {row['total']}\n"
        f"Active: {row['active']}\n"
        f"Expired: {row['expired']}\n"
        f"Bound: {row['bound']}\n"
        f"Banned: {row['banned']}"
    )


class VerifyRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=512)


class VerifyResponse(BaseModel):
    ok: bool
    message: str
    expires_at: datetime | None = None
    first_activation: bool = False


def verify_secret(value: str | None):
    if not value or not secrets.compare_digest(value, API_SECRET):
        raise HTTPException(status_code=401, detail="Invalid API secret")


@app.get("/")
def root():
    return {"ok": True, "service": "GUDU X BYPASS Keysystem"}


@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return {"ok": True, "database": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/api/verify", response_model=VerifyResponse)
def verify_license(
    payload: VerifyRequest,
    x_api_secret: str | None = Header(default=None),
):
    verify_secret(x_api_secret)

    key = payload.key.strip().upper()
    device = normalize_device(payload.device_id)
    dhash = device_hash(device)
    now = utcnow()

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM licenses WHERE license_key=%s FOR UPDATE",
            (key,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Invalid key")

        if row["banned"]:
            raise HTTPException(
                status_code=403,
                detail=row["ban_reason"] or "Key is banned",
            )

        if row["expires_at"] <= now:
            raise HTTPException(status_code=403, detail="Key expired")

        first_activation = False

        if row["device_hash"] is None:
            conn.execute(
                """
                UPDATE licenses
                SET device_id=%s,
                    device_hash=%s,
                    activated_at=COALESCE(activated_at, NOW()),
                    last_seen_at=NOW(),
                    total_checks=total_checks+1
                WHERE license_key=%s
                """,
                (device, dhash, key),
            )
            first_activation = True
        elif not secrets.compare_digest(row["device_hash"], dhash):
            raise HTTPException(
                status_code=403,
                detail="Key is already bound to another device",
            )
        else:
            conn.execute(
                """
                UPDATE licenses
                SET last_seen_at=NOW(),
                    total_checks=total_checks+1
                WHERE license_key=%s
                """,
                (key,),
            )

        conn.commit()

    return VerifyResponse(
        ok=True,
        message="Activated successfully" if first_activation else "Verified",
        expires_at=row["expires_at"],
        first_activation=first_activation,
    )


@app.on_event("startup")
async def startup():
    global telegram_app
    init_db()

    telegram_app = Application.builder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("help", cmd_start))
    telegram_app.add_handler(CommandHandler("gen", cmd_gen))
    telegram_app.add_handler(CommandHandler("reset", cmd_reset))
    telegram_app.add_handler(CommandHandler("ban", cmd_ban))
    telegram_app.add_handler(CommandHandler("unban", cmd_unban))
    telegram_app.add_handler(CommandHandler("extend", cmd_extend))
    telegram_app.add_handler(CommandHandler("delete", cmd_delete))
    telegram_app.add_handler(CommandHandler("info", cmd_info))
    telegram_app.add_handler(CommandHandler("list", cmd_list))
    telegram_app.add_handler(CommandHandler("stats", cmd_stats))

    await telegram_app.initialize()
    await telegram_app.start()
    if telegram_app.updater:
        await telegram_app.updater.start_polling(drop_pending_updates=True)

    log.info("Keysystem started")


@app.on_event("shutdown")
async def shutdown():
    global telegram_app
    if telegram_app:
        if telegram_app.updater:
            await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        telegram_app = None


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
