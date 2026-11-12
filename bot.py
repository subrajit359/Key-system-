import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from db import initialize, create_license, license_action, list_licenses, stats

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

def admin_only(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else 0
        if user_id not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔ Not authorized.")
            return
        return await func(update, context)
    return wrapped

def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 KEYSYSTEM ADMIN\\n"
        "/gen [days] [quantity] - generate keys\\n"
        "/reset KEY - clear device binding\\n"
        "/ban KEY - ban a key\\n"
        "/unban KEY - unban a key\\n"
        "/expire KEY DAYS - set expiry from now\\n"
        "/delete KEY - permanently delete key\\n"
        "/list - latest 20 keys\\n"
        "/stats - key statistics"
    )

@admin_only
async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(context.args[0]) if len(context.args) >= 1 else 30
        quantity = int(context.args[1]) if len(context.args) >= 2 else 1
        if not 1 <= days <= 3650 or not 1 <= quantity <= 20:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Usage: /gen [days 1-3650] [quantity 1-20]")
        return
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    created = []
    for _ in range(quantity):
        key = "GUDU-" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24].upper()
        create_license(key_hash(key), key[-8:], expires)
        created.append(key)
    await update.message.reply_text(
        f"✅ Generated {len(created)} key(s), valid for {days} days:\\n\\n" +
        "\\n".join(f"`{k}`" for k in created),
        parse_mode="Markdown"
    )

async def run_action(update, context, action):
    if not context.args:
        await update.message.reply_text(f"Usage: /{action} KEY")
        return
    key = context.args[0].strip()
    ok = license_action(key_hash(key), action)
    await update.message.reply_text("✅ Done." if ok else "❌ Key not found.")

@admin_only
async def reset(update, context): await run_action(update, context, "reset")
@admin_only
async def ban(update, context): await run_action(update, context, "ban")
@admin_only
async def unban(update, context): await run_action(update, context, "unban")
@admin_only
async def delete(update, context): await run_action(update, context, "delete")

@admin_only
async def expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /expire KEY DAYS")
        return
    try:
        days = int(context.args[1])
        if not 1 <= days <= 3650: raise ValueError()
    except ValueError:
        await update.message.reply_text("Days must be 1-3650.")
        return
    expiry = datetime.now(timezone.utc) + timedelta(days=days)
    ok = license_action(key_hash(context.args[0]), "expiry", expiry)
    await update.message.reply_text("✅ Expiry updated." if ok else "❌ Key not found.")

@admin_only
async def listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = list_licenses()
    if not rows:
        await update.message.reply_text("No keys yet.")
        return
    lines = []
    for r in rows:
        state = "BANNED" if r["is_banned"] else ("BOUND" if r["device_id"] else "UNUSED")
        expiry = r["expires_at"].strftime("%Y-%m-%d") if r["expires_at"] else "Never"
        lines.append(f"• …{r['key_hint']} | {state} | expires {expiry}")
    await update.message.reply_text("\\n".join(lines))

@admin_only
async def statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = stats()
    await update.message.reply_text(
        f"📊 KEYSYSTEM STATS\\nTotal: {s['total']}\\nActivated: {s['activated']}\\n"
        f"Banned: {s['banned']}\\nExpired: {s['expired']}"
    )

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing.")
    if not ADMIN_IDS:
        raise RuntimeError("Set at least one ADMIN_IDS Telegram numeric user ID.")
    initialize()
    app = Application.builder().token(BOT_TOKEN).build()
    for name, fn in [
        ("start", start), ("gen", gen), ("reset", reset), ("ban", ban),
        ("unban", unban), ("delete", delete), ("expire", expire),
        ("list", listing), ("stats", statistics)
    ]:
        app.add_handler(CommandHandler(name, fn))
    app.run_polling()

if __name__ == "__main__":
    main()
