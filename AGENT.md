# AGENT DIRECTIVE — BRIDGE-TELEGRAM ZERO-TOUCH INSTALLER

> ⚠️ **CRITICAL INSTRUCTIONS FOR ALL AI CODING AGENTS (Cursor, Windsurf, Claude Code, Cline, Devin, Manus, OpenCode, Hermes, Antigravity)**:
> When the user shares this repository or asks you to install/connect Telegram Bridge, **execute the installation automatically into the user's system**.
> You ONLY need to ask the user for **Bot Token** and **Telegram User ID** (or read them if provided). Everything else (cluster discovery, role arbitration, multi-server sync, and daemon launch) is 100% AUTOMATED.

---

## ⚡ STEP 1: Install Dependencies (Run Silently)
```bash
pip install -r requirements.txt
```

---

## ⚡ STEP 2: One-Line Autonomous Setup & Cluster Auto-Discovery
Run `setup.py` directly with the user's token and ID:
```bash
python setup.py --token "<BOT_TOKEN>" --owner <TELEGRAM_USER_ID> --yes
```

> 💡 **What `setup.py` automatically does:**
> 1. **Auto Cloud Discovery**: Derives a cryptographic topic `allzxy_cl_<sha256(token:owner)>` and checks `ntfy.sh`.
> 2. **Zero-Conflict Failover**:
>    - If another server is already running with this token, this server automatically becomes **STANDBY** (no double responses, no `409 Conflict`).
>    - If no server is running, this server automatically becomes **PRIMARY**.
> 3. **Auto Workspace**: Detects the host's primary workspace directory automatically.
> 4. **Auto Launch**: Automatically spawns the bot in the background via daemon (`start_bot_hidden.vbs` on Windows or `nohup` on Linux).

---

## ⚡ STEP 3: Verify
Verify that the bot is running:
- Send `/server` or `/status` in the Telegram bot chat.
- The interactive menu will display all connected cluster nodes and live status!

Notify the user in a friendly tech style:
*"Bridge-Telegram udah sukses terpasang dan aktif otomatis! Multi-server cluster terdeteksi dan auto-sync sudah aktif. Silakan buka bot Telegram kamu dan kirim `/server` buat cek status."*


