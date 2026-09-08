# AGENT DIRECTIVE — BRIDGE-TELEGRAM ZERO-TOUCH INSTALLER

> ⚠️ **CRITICAL FOR ALL AI CODING AGENTS (Cursor, Windsurf, Claude Code, Cline, Devin, Manus, OpenCode, Hermes, Antigravity)**:
> When the user shares this repository or asks you to install/connect Telegram Bridge, **DO NOT ASK TECHNICAL QUESTIONS**. Follow the 3-step zero-touch deployment below.

---

## ⚡ STEP 1: Dependencies (Run Silently)
Install the required packages immediately:
```bash
pip install -r requirements.txt
```

---

## ⚡ STEP 2: Credentials & Auto-Config
1. Check if `config.json` already exists in this folder.
2. If NOT, copy `config.example.json` to `config.json`.
3. Set `"backend_provider": "auto"` (the engine will self-detect whether you are Antigravity, Hermes, 9Router, OpenAI, or CLI).
4. Prompt the user **ONLY for the 2 essential credentials** if not yet provided:
   - **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
   - **Telegram User ID** (numeric ID from [@userinfobot](https://t.me/userinfobot))
5. Write them into `config.json`.

---

## ⚡ STEP 3: Launch Service & Verify
Launch the gateway:
- **Windows**: Run `Auto Run/start_bot_hidden.vbs` (runs in background) or `python bridge_telegram.py`.
- **Linux / macOS**: `nohup python3 bridge_telegram.py > bridge_telegram.log 2>&1 &`

Verify the bot started by checking that `bridge_telegram.log` contains:
`Bridge-Telegram is running and polling for updates...`

Tell the user: *"Bridge-Telegram udah aktif dan connect ke chat Telegram! Silakan buka bot dan ketik `/start` buat mulai kontrol."*
