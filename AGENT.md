# AGENT DIRECTIVE — BRIDGE-TELEGRAM ZERO-TOUCH INSTALLER

> ⚠️ **CRITICAL INSTRUCTIONS FOR ALL AI CODING AGENTS (Cursor, Windsurf, Claude Code, Cline, Devin, Manus, OpenCode, Hermes, Antigravity)**:
> When the user shares this repository link or instructs you to install/connect Telegram Bridge, **execute the installation automatically into the user's system**.
> DO NOT hardcode or create paths like `E:\Alfan\telegram-bridge` — that path was solely the author's development environment. Install directly in the current workspace or designated tools directory.

---

## ⚡ STEP 1: Dependencies (Run Silently)
Install the required packages immediately:
```bash
pip install -r requirements.txt
```

---

## ⚡ STEP 2: Workspace & Credentials Setup
1. Check if `config.json` already exists in this folder.
2. If NOT, copy `config.example.json` to `config.json`.
3. Set `"backend_provider": "auto"` (the bridge automatically detects whether you are Antigravity, Hermes, 9Router, OpenAI, or CLI).
4. **Ask the user for their desired Workspace directory & credentials**:
   - **Workspace Directory**: Ask the user: *"Di folder mana kamu mau bot ini bekerja dan menyimpan project / tugas / analisis file? (contoh: `E:\Projects` atau `C:\Users\<user>\Workspace`)*". Set this path into `"working_directory"`.
   - **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather)). Set into `"bot_token"`.
   - **Telegram User ID** (numeric ID from [@userinfobot](https://t.me/userinfobot)). Set into `"authorized_user_id"`.
5. Set `"downloads_directory"` to `<working_directory>/downloads` (or `./downloads`).
6. Write these values into `config.json`.

---

## ⚡ STEP 3: Launch Service & Verify
Launch the gateway:
- **Windows**: Run `Auto Run/start_bot_hidden.vbs` (runs quietly in background) or `python bridge_telegram.py`.
- **Linux / macOS**: `nohup python3 bridge_telegram.py > bridge_telegram.log 2>&1 &`

Verify the bot started by checking that `bridge_telegram.log` contains:
`Bridge-Telegram is running and polling for updates...`

Notify the user in a friendly tech style:
*"Bridge-Telegram udah berhasil terpasang dan aktif di sistem! Workspace diatur ke `[path-workspace]`. Silakan buka bot Telegram kamu dan kirim `/start` buat mulai kontrol."*

