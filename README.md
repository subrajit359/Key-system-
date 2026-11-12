# Keysystem

A flat-file Python license server and Telegram admin bot backed by PostgreSQL.
All project files live directly inside `Keysystem/`; no subfolders are needed.

## Features

- Generate one or many time-limited licence keys from Telegram.
- First successful activation binds a key to one device ID.
- The same device can verify again; another device is rejected.
- Reset binding, ban/unban, change expiry, delete keys.
- List recent keys and view statistics.
- Store only SHA-256 hashes of licence keys in PostgreSQL.

## Important device-binding limitation

The API enforces one `device_id` per key, but a plain Lua-generated device ID can be copied or spoofed. This is practical one-device licensing, not strong hardware-backed protection. For stronger protection, add an Android helper that creates a private key in Android Keystore and signs server challenges. Never put database credentials, bot tokens, or admin secrets in Lua.

## Setup

1. Create a PostgreSQL database with your provider.
2. Copy `.env.example` to `.env` and fill in `DATABASE_URL`, `BOT_TOKEN`, and your numeric Telegram ID in `ADMIN_IDS`.
3. Install Python 3.11+ and dependencies:

   `python -m pip install -r requirements.txt`

4. Start the API in one terminal:

   `python -m uvicorn app:app --host 0.0.0.0 --port 8000`

5. Start the Telegram bot in another terminal:

   `python bot.py`

6. Put the API behind HTTPS before connecting your Lua client. Do not expose port 8000 directly to the public internet without a reverse proxy and HTTPS.

## Telegram commands

- `/gen` — one key, 30 days
- `/gen 90 5` — five keys, 90 days
- `/reset GUDU-...` — unbind the current device
- `/ban GUDU-...`
- `/unban GUDU-...`
- `/expire GUDU-... 30` — set expiry to 30 days from now
- `/delete GUDU-...` — permanently delete
- `/list`
- `/stats`

Only Telegram IDs listed in `ADMIN_IDS` can run commands. Keep `.env` private and do not upload it to a public repository.

## API

`POST /v1/license/activate` and `POST /v1/license/verify`

JSON body:

```json
{
  "key": "GUDU-YOUR-LICENSE-KEY",
  "device_id": "stable-device-identifier"
}
```

Example response:

```json
{"valid": true, "status": "activated"}
```

Possible failure statuses: `invalid_key`, `banned`, `expired`, `device_mismatch`.

The client must send the same stable device ID for subsequent checks. Use HTTPS. A production deployment should also add request rate limiting, monitoring, backups, and cryptographic device proof if stronger binding is required.
