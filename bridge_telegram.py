#!/usr/bin/env python3
"""
Bridge-Telegram — Universal Autonomous AI Agent Gateway
Synchronized with AI CLI binaries, API backends, and multi-modal channels.
"""

import asyncio
import ctypes
import datetime
import html
import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Dict, List, Optional, Any

import psutil
from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config_manager import config_mgr
from engine_adapters import (
    AntigravityAdapter,
    OpenAICompatibleAdapter,
    SubprocessCLIAdapter,
    BaseAgentAdapter,
    auto_detect_engine,
)

# --- CONFIGURATION & PATHS (DYNAMICALLY MANAGED) ---
_cfg = config_mgr.config
BOT_TOKEN = _cfg.get("bot_token", "")
AUTHORIZED_USER_ID = int(_cfg.get("authorized_user_id", 0))

# Adaptive Engine Auto-Detection
_raw_provider = _cfg.get("backend_provider", "auto")
if not _raw_provider or _raw_provider.lower() == "auto":
    BACKEND_PROVIDER, _detect_reason = auto_detect_engine(_cfg)
else:
    BACKEND_PROVIDER = _raw_provider
    _detect_reason = f"Explicitly configured: {BACKEND_PROVIDER}"

WORKSPACE_DIR = Path(_cfg.get("working_directory") or Path.cwd())
BRIDGE_DIR = Path(__file__).resolve().parent
ANTIGRAVITY_HUB = Path(_cfg.get("antigravity", {}).get("hub_path") or (WORKSPACE_DIR / "antigravity"))
AGY_EXE = Path(_cfg.get("antigravity", {}).get("binary_path") or "agy.exe")

SETTINGS_FILE = WORKSPACE_DIR / ".gemini" / "antigravity-cli" / "settings.json"
SESSION_FILE = BRIDGE_DIR / "active_session.json"
QUOTA_FILE = BRIDGE_DIR / "quota_state.json"
SERVER_STATE_FILE = BRIDGE_DIR / "server_state.json"
TASK_STATE_FILE = BRIDGE_DIR / "task_state.json"
DOWNLOADS_DIR = Path(_cfg.get("downloads_directory") or (BRIDGE_DIR / "downloads"))
AGENTS_MD = ANTIGRAVITY_HUB / "AGENTS.md" if (ANTIGRAVITY_HUB / "AGENTS.md").exists() else WORKSPACE_DIR / "AGENTS.md"
GEMINI_MD = ANTIGRAVITY_HUB / "GEMINI.md" if (ANTIGRAVITY_HUB / "GEMINI.md").exists() else WORKSPACE_DIR / "GEMINI.md"
BRAIN_DIR = WORKSPACE_DIR / ".gemini" / "antigravity-cli" / "brain"

# Ensure runtime directories exist
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Setup Logging
LOG_FILE = BRIDGE_DIR / "bridge_telegram.log"
_handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
    _handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s",
    level=logging.INFO,
    handlers=_handlers,
)
logger = logging.getLogger("BridgeTelegram")

# --- MODEL DEFINITIONS & SHORTCUTS ---
OFFICIAL_MODELS = {
    "gemini-3.8-flash-high": "Gemini 3.8 Flash (High)",
    "gemini-3.8-flash-medium": "Gemini 3.8 Flash (Medium)",
    "gemini-3.8-flash-low": "Gemini 3.8 Flash (Low)",
    "gemini-3.7-flash-high": "Gemini 3.7 Flash (High)",
    "gemini-3.7-flash-medium": "Gemini 3.7 Flash (Medium)",
    "gemini-3.7-flash-low": "Gemini 3.7 Flash (Low)",
    "gemini-3.6-flash-high": "Gemini 3.6 Flash (High)",
    "gemini-3.6-flash-medium": "Gemini 3.6 Flash (Medium)",
    "gemini-3.6-flash-low": "Gemini 3.6 Flash (Low)",
    "gemini-3.1-pro-high": "Gemini 3.1 Pro (High)",
    "gemini-3.1-pro-low": "Gemini 3.1 Pro (Low)",
    "claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
    "claude-opus-4-6-thinking": "Claude Opus 4.6 (Thinking)",
    "gpt-oss-120b-medium": "GPT-OSS 120B (Medium)",
}

MODEL_SHORTCUTS = {
    "3.8": "Gemini 3.8 Flash (High)",
    "3.8-high": "Gemini 3.8 Flash (High)",
    "3.8-med": "Gemini 3.8 Flash (Medium)",
    "3.8-low": "Gemini 3.8 Flash (Low)",
    "3.7": "Gemini 3.7 Flash (High)",
    "3.7-high": "Gemini 3.7 Flash (High)",
    "3.7-med": "Gemini 3.7 Flash (Medium)",
    "3.7-low": "Gemini 3.7 Flash (Low)",
    "3.6": "Gemini 3.6 Flash (High)",
    "pro": "Gemini 3.1 Pro (High)",
    "pro-high": "Gemini 3.1 Pro (High)",
    "pro-low": "Gemini 3.1 Pro (Low)",
    "sonnet": "Claude Sonnet 4.6 (Thinking)",
    "opus": "Claude Opus 4.6 (Thinking)",
    "gpt": "GPT-OSS 120B (Medium)",
}

# --- REALTIME SESSION & BRAIN SYNC ENGINE ---

def get_brain_sessions(limit: int = 10) -> List[Dict[str, Any]]:
    """Lists recent session directories from brain, sorted by transcript last modification time."""
    if not BRAIN_DIR.exists():
        return []
    
    sessions_list = []
    try:
        for item in BRAIN_DIR.iterdir():
            if not item.is_dir():
                continue
            transcript_file = item / ".system_generated" / "logs" / "transcript.jsonl"
            if not transcript_file.exists():
                continue
            
            try:
                mtime = transcript_file.stat().st_mtime
                sessions_list.append({
                    "id": item.name,
                    "path": item,
                    "transcript_file": transcript_file,
                    "mtime": mtime,
                    "datetime_str": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error listing brain sessions: {e}")
    
    sessions_list.sort(key=lambda x: x["mtime"], reverse=True)
    return sessions_list[:limit]

def get_session_details(conv_id: str) -> Dict[str, Any]:
    """Extracts summary, turn count, and last conversation turn from a session transcript."""
    transcript_file = BRAIN_DIR / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    details = {
        "id": conv_id,
        "turns": 0,
        "last_user_prompt": "",
        "last_response": "",
        "exists": transcript_file.exists(),
        "mtime": transcript_file.stat().st_mtime if transcript_file.exists() else 0,
        "datetime_str": datetime.datetime.fromtimestamp(transcript_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if transcript_file.exists() else "-",
    }
    if not transcript_file.exists():
        return details
    
    try:
        with open(transcript_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    t = row.get("type")
                    if t == "USER_INPUT":
                        details["turns"] += 1
                        raw_c = row.get("content", "")
                        if "<USER_REQUEST>" in raw_c:
                            raw_c = raw_c.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                        details["last_user_prompt"] = raw_c
                    elif t == "PLANNER_RESPONSE":
                        details["last_response"] = row.get("content", "").strip()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Error reading transcript for {conv_id}: {e}")
    
    return details

def is_cli_interactive_running() -> bool:
    """
    Checks if an interactive agy.exe CLI process is actively running in the terminal.
    Prevents concurrent session collisions on the same conversation ID.
    """
    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            name = (p.info.get('name') or '').lower()
            if 'agy' in name:
                cmd = p.info.get('cmdline') or []
                # If it's agy without -p / --print / --prompt, it's an interactive terminal session
                if not any(arg in cmd for arg in ['-p', '--print', '--prompt']):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

# --- PERSISTENT CREDENTIAL VAULT ENGINE ---
AUTH_VAULT_BACKUP = WORKSPACE_DIR / ".gemini" / "antigravity-cli" / ".auth_vault_backup.json"

class _WIN_CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]

def protect_and_restore_auth_vault() -> bool:
    """
    Guarantees Google Antigravity credentials in Windows Credential Manager are
    persistently preserved, automatically backed up, and restored if missing.
    Prevents unexpected automatic logouts when CLI is closed or restarted.
    """
    if platform.system() != "Windows":
        return True
    
    try:
        advapi32 = ctypes.windll.advapi32
        cred_ptr = ctypes.POINTER(_WIN_CREDENTIAL)()
        
        # 1. Try reading existing credential from Windows Vault
        if advapi32.CredReadW('gemini:antigravity', 1, 0, ctypes.byref(cred_ptr)):
            c = cred_ptr.contents
            blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
            advapi32.CredFree(cred_ptr)
            # Persist backup to disk
            AUTH_VAULT_BACKUP.parent.mkdir(parents=True, exist_ok=True)
            with open(AUTH_VAULT_BACKUP, "wb") as f:
                f.write(blob)
            return True
        else:
            # 2. Missing from Windows Credential Manager! Auto-restore from backup!
            if AUTH_VAULT_BACKUP.exists():
                with open(AUTH_VAULT_BACKUP, "rb") as f:
                    blob_data = f.read()
                
                cred = _WIN_CREDENTIAL()
                cred.Flags = 0
                cred.Type = 1  # CRED_TYPE_GENERIC
                cred.TargetName = 'gemini:antigravity'
                cred.Comment = 'Bridge-Telegram Persistent Vault'
                cred.CredentialBlobSize = len(blob_data)
                cred.CredentialBlob = (ctypes.c_byte * len(blob_data))(*blob_data)
                cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
                cred.AttributeCount = 0
                cred.Attributes = None
                cred.TargetAlias = None
                cred.UserName = 'antigravity'
                
                ok = advapi32.CredWriteW(ctypes.byref(cred), 0)
                if ok:
                    logger.info("Successfully self-healed and restored gemini:antigravity credentials in Windows Credential Manager!")
                    return True
                else:
                    logger.error("CredWriteW failed to restore credential.")
    except Exception as e:
        logger.error(f"Error managing auth vault: {e}")
    return False

class AntigravitySession:
    def __init__(self):
        protect_and_restore_auth_vault()
        self.conversation_id: Optional[str] = None
        self.telegram_conv_id: Optional[str] = None
        self.turns: int = 0
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0
        self.last_thinking_tokens: int = 0
        self.last_total_tokens: int = 0
        self.cumulative_total_tokens: int = 0
        self.last_duration: float = 0.0
        self.active_model: str = "Gemini 3.8 Flash (High)"
        self.working_dir: Path = WORKSPACE_DIR
        self.context_window_limit: int = 1_000_000
        self.auto_sync_cli: bool = True
        self.last_sync_mtime: float = 0.0
        self.last_settings_mtime: float = 0.0
        self.start_time = datetime.datetime.now()
        self.load_session()
        self.sync_model_from_settings(force=True)

    def load_session(self):
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_cid = data.get("conversation_id")
                    self.conversation_id = raw_cid if raw_cid else None
                    self.telegram_conv_id = data.get("telegram_conv_id")
                    self.turns = data.get("turns", 0)
                    self.last_input_tokens = data.get("last_input_tokens", 0)
                    self.last_output_tokens = data.get("last_output_tokens", 0)
                    self.last_thinking_tokens = data.get("last_thinking_tokens", 0)
                    self.last_total_tokens = data.get("last_total_tokens", 0)
                    self.cumulative_total_tokens = data.get("cumulative_total_tokens", 0)
                    self.active_model = data.get("active_model", "Gemini 3.8 Flash (High)")
                    self.auto_sync_cli = data.get("auto_sync_cli", True)
                    self.last_sync_mtime = data.get("last_sync_mtime", 0.0)
                    saved_wd = data.get("working_dir")
                    if saved_wd and Path(saved_wd).exists():
                        self.working_dir = Path(saved_wd)
            except Exception as e:
                logger.error(f"Error loading active_session.json: {e}")

    def save_session(self):
        try:
            BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "conversation_id": self.conversation_id,
                "telegram_conv_id": self.telegram_conv_id,
                "turns": self.turns,
                "last_input_tokens": self.last_input_tokens,
                "last_output_tokens": self.last_output_tokens,
                "last_thinking_tokens": self.last_thinking_tokens,
                "last_total_tokens": self.last_total_tokens,
                "cumulative_total_tokens": self.cumulative_total_tokens,
                "active_model": self.active_model,
                "auto_sync_cli": self.auto_sync_cli,
                "last_sync_mtime": self.last_sync_mtime,
                "working_dir": str(self.working_dir),
            }
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving active_session.json: {e}")

    def sync_model_from_settings(self, force: bool = False) -> Optional[str]:
        """
        Bidirectional synchronization from CLI settings.json to Telegram session.
        If settings.json has been modified (by CLI /model or terminal changes),
        or if force=True, updates self.active_model and saves to active_session.json.
        Returns the new model name if changed, otherwise None.
        """
        if not SETTINGS_FILE.exists():
            return None
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
            if not force and mtime <= self.last_settings_mtime:
                return None
            
            self.last_settings_mtime = mtime
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            target_model = data.get("model")
            if target_model and target_model != self.active_model:
                old_model = self.active_model
                self.active_model = target_model
                self.save_session()
                logger.info(f"Synchronized model from settings.json (CLI -> Chat): {old_model} -> {target_model}")
                return target_model
        except Exception as e:
            logger.error(f"Error reading model from settings.json: {e}")
        return None

    def update_model_to_settings(self, new_model: str) -> bool:
        """
        Bidirectional synchronization from Telegram session to CLI settings.json.
        Updates self.active_model, saves active_session.json, and writes new_model to settings.json
        so that subsequent CLI sessions immediately run with this model.
        """
        self.active_model = new_model
        self.save_session()
        try:
            cfg = {}
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["model"] = new_model
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            self.last_settings_mtime = SETTINGS_FILE.stat().st_mtime
            logger.info(f"Synchronized model to settings.json (Chat -> CLI): {new_model}")
            return True
        except Exception as e:
            logger.error(f"Error saving model to settings.json: {e}")
            return False

    def check_and_sync_with_latest_cli(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        If auto_sync_cli is enabled (or force=True), checks if there is a more recent conversation
        or updated turns in the brain directory.
        Only syncs when the interactive CLI is not running (unless force=True), avoiding stream collision.
        """
        if not self.auto_sync_cli and not force:
            return None
        
        if is_cli_interactive_running() and not force:
            return None
        
        recent_sessions = get_brain_sessions(limit=1)
        if not recent_sessions:
            return None
        
        latest = recent_sessions[0]
        latest_id = latest["id"]
        latest_mtime = latest["mtime"]
        
        needs_sync = False
        if not self.conversation_id:
            needs_sync = True
        elif latest_id != self.conversation_id and latest_mtime > self.last_sync_mtime + 2:
            needs_sync = True
        elif latest_id == self.conversation_id and latest_mtime > self.last_sync_mtime + 2:
            needs_sync = True
        elif force:
            needs_sync = True

        if needs_sync:
            info = get_session_details(latest_id)
            if force or info["turns"] != self.turns or latest_id != self.conversation_id or latest_mtime > self.last_sync_mtime:
                logger.info(f"Syncing CLI session state: {latest_id} (Turns: {info['turns']}, Mtime: {latest_mtime})")
                self.conversation_id = latest_id
                self.turns = info["turns"]
                self.last_sync_mtime = latest_mtime
                self.save_session()
                return info
        return None

    def update_usage(self, conv_id: Optional[str], usage_data: dict, duration: float, num_turns: int):
        if conv_id:
            self.conversation_id = conv_id
        self.last_input_tokens = usage_data.get("input_tokens", 0)
        self.last_output_tokens = usage_data.get("output_tokens", 0)
        self.last_thinking_tokens = usage_data.get("thinking_tokens", 0)
        self.last_total_tokens = usage_data.get("total_tokens", 0)
        self.cumulative_total_tokens += self.last_total_tokens
        self.last_duration = duration
        self.turns = num_turns if num_turns > 0 else self.turns + 1
        self.last_sync_mtime = time.time()
        self.save_session()

    def reset_session(self):
        self.conversation_id = None
        self.telegram_conv_id = None
        self.turns = 0
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        self.last_thinking_tokens = 0
        self.last_total_tokens = 0
        self.cumulative_total_tokens = 0
        self.last_duration = 0.0
        self.last_sync_mtime = 0.0
        self.start_time = datetime.datetime.now()
        self.save_session()

session = AntigravitySession()

def get_system_directive_header() -> str:
    for fpath in [AGENTS_MD, GEMINI_MD]:
        if fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    return f"[SYSTEM DIRECTIVES & ARCHITECTURE]\n{f.read()}\n\n[USER REQUEST]\n"
            except Exception as e:
                logger.error(f"Error reading {fpath}: {e}")
    return "[SYSTEM: You are an expert, production-grade autonomous AI assistant. Tone: respectful, sharp, direct, concise, full autonomy.]\n"

is_turn_in_progress = False
current_running_task_desc = ""
current_task_start_time = 0.0

# --- ADAPTER ROUTER & EXECUTION ENGINE ---
def get_active_adapter() -> BaseAgentAdapter:
    prov = BACKEND_PROVIDER.lower()
    if prov in ["openai_compatible", "openai"]:
        o_cfg = _cfg.get("openai_compatible", {})
        return OpenAICompatibleAdapter(
            api_base=o_cfg.get("api_base", "https://api.openai.com/v1"),
            api_key=o_cfg.get("api_key", ""),
            default_model=o_cfg.get("model", "gpt-4o"),
            system_prompt=o_cfg.get("system_prompt", ""),
        )
    elif prov in ["nine_router", "9router"]:
        nr_cfg = _cfg.get("nine_router", {})
        return OpenAICompatibleAdapter(
            api_base=nr_cfg.get("api_base", "https://api.9router.com/v1"),
            api_key=nr_cfg.get("api_key", ""),
            default_model=nr_cfg.get("model", "deepseek-chat"),
            system_prompt="You are an autonomous AI engineering assistant powered by 9Router.",
        )
    elif prov in ["hermes", "ollama"]:
        h_cfg = _cfg.get("hermes", {})
        return OpenAICompatibleAdapter(
            api_base=h_cfg.get("api_base", "http://localhost:11434/v1"),
            api_key=h_cfg.get("api_key", "ollama"),
            default_model=h_cfg.get("model", "hermes-3-llama-3.1-8b"),
            system_prompt="You are an expert autonomous Hermes AI agent.",
        )
    elif prov in ["cli_agent", "opencode", "claude_code"]:
        c_cfg = _cfg.get("cli_agent", {})
        return SubprocessCLIAdapter(
            binary_path=c_cfg.get("binary_path", "opencode"),
            args_template=c_cfg.get("args_template", ["-p", "{prompt}"]),
        )
    else:
        # Default: Google Antigravity
        return AntigravityAdapter(
            binary_path=AGY_EXE,
            timeout=float(_cfg.get("antigravity", {}).get("timeout_seconds", 180.0)),
        )

# --- EXECUTION BRIDGE TO AGY.EXE / MULTI-BACKEND ENGINE ---
async def execute_agy_turn(prompt: str, model: Optional[str] = None, max_retries: int = 2) -> tuple[str, Optional[dict]]:
    """
    Executes a turn directly through the active backend adapter (Google Antigravity, 9Router, Hermes, etc.)
    and captures true AI response + realtime token metrics.
    Includes autonomous retry for transient network hiccups, stream interruptions, and active CLI terminal stream protection.
    """
    global is_turn_in_progress, current_running_task_desc, current_task_start_time
    is_turn_in_progress = True
    current_running_task_desc = prompt
    current_task_start_time = time.time()

    # Record task start persistently for multi-server failover recovery
    target_cid = session.telegram_conv_id or session.conversation_id
    record_task_start(prompt=prompt, conv_id=target_cid, model=model or session.active_model)

    # If backend is not Antigravity, delegate directly to active provider adapter
    if BACKEND_PROVIDER.lower() not in ["antigravity", "agy"]:
        try:
            adapter = get_active_adapter()
            resp, data = await adapter.execute_turn(
                prompt=prompt,
                session_id=session.telegram_conv_id or session.conversation_id,
                model=model,
                working_dir=session.working_dir,
            )
            session.turns += 1
            session.save_session()
            record_task_end(response_summary=resp, success=True)
            return (resp, data)
        except Exception as ex:
            logger.error(f"Error in backend adapter {BACKEND_PROVIDER}: {ex}")
            record_task_end(response_summary=str(ex), success=False)
            return (f"⚠️ *Provider Adapter Error ({BACKEND_PROVIDER}):*\n`{str(ex)}`", None)
        finally:
            is_turn_in_progress = False
            current_running_task_desc = ""
            current_task_start_time = 0.0

    # Auto-sync with recent CLI session if terminal is closed
    synced_info = session.check_and_sync_with_latest_cli()
    if synced_info:
        logger.info(f"Auto-synced with active CLI session: {synced_info['id']} (turns: {synced_info['turns']})")

    cli_active = is_cli_interactive_running()
    target_conv_id = None
    
    if cli_active:
        # Avoid clashing with the active interactive CLI session in terminal
        target_conv_id = session.telegram_conv_id
        logger.info(f"Interactive CLI is open in terminal. Using isolated Telegram session: {target_conv_id or 'New'}")
    else:
        # Terminal is closed: use dedicated Telegram session if available, otherwise conversation_id
        target_conv_id = session.telegram_conv_id or session.conversation_id

    DIRECTIVE_REMINDER = (
        "\n\n[DIRECTIVE: Sampaikan seluruh jawaban, penjelasan, dan hasil langsung di chat. "
        "DILARANG KERAS membuat file artifact markdown (.md di folder brain). "
        "Jika menyajikan berkas/gambar, sebutkan path lokal absolutnya secara langsung agar sistem Telegram dapat mengirimkannya langsung ke chat. "
        "Jika pada pelaksanaan tugas membutuhkan persetujuan atau konfirmasi dari user, kirimkan permintaan persetujuannya secara jelas langsung ke chat. "
        "Untuk setiap tugas project coding, pembuatan script/aplikasi baru, analisis atau kloning repository, serta tugas yang membutuhkan tempat menyimpan hasil/analisis, WAJIB buat folder baru dan simpan di dalam 'E:\\Alfan\\<nama-project-atau-tugas>'. "
        "ADAPTASI BAHASA & TONE: Jika user menggunakan gaya bahasa santai, gaul, kasual, atau khas sosmed (e.g. lu/gue, bro, ngab, dong, nih, wkwk, santai), balas dengan gaya bahasa gaul/sosmed yang luwes, santai, asik, ekspresif, dan natural layaknya teman tech yang pro, jangan kaku atau terdengar seperti template robot AI formal. Jika user berbicara formal atau teknis serius, sesuaikan dengan nada profesional dan presisi. "
        "FORMAT OUTPUT: Jangan gunakan terlalu banyak tanda bintang (*) atau simbol dekoratif berlebih. Bold secukupnya saja pada kata penting, manfaatkan fitur quote (>) dan inline code (`...`) atau code block agar tampilan pesan simple, elegan, bersih, dan detail teknisnya tetap jelas.]"
    )
    actual_prompt = prompt + DIRECTIVE_REMINDER
    if not target_conv_id or session.turns == 0:
        actual_prompt = get_system_directive_header() + prompt + DIRECTIVE_REMINDER

    active_cwd = session.working_dir if session.working_dir.exists() else WORKSPACE_DIR
    cmd = [
        str(AGY_EXE),
        "--dangerously-skip-permissions",
        "--output-format", "json",
        "-p", actual_prompt,
    ]
    if active_cwd != WORKSPACE_DIR:
        cmd.extend(["--add-dir", str(active_cwd)])

    if target_conv_id:
        cmd.extend(["--conversation", target_conv_id])
    elif not cli_active and session.conversation_id:
        cmd.extend(["--conversation", session.conversation_id])

    session.sync_model_from_settings()
    current_model = model or session.active_model
    if current_model:
        cmd.extend(["--model", current_model])

    logger.info(f"Running AGY turn: {prompt[:60]}... (Target Conv: {target_conv_id or 'New'}) [CWD: {active_cwd}] [Model: {current_model}]")
    
    kwargs: dict = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # subprocess.CREATE_NO_WINDOW

    last_error_data = None
    last_err_msg = ""
    is_turn_in_progress = True

    try:
        for attempt in range(max_retries + 1):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(active_cwd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **kwargs,
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    logger.error(f"AGY process timed out on attempt {attempt+1}")
                    if attempt < max_retries:
                        await asyncio.sleep(2.0)
                        continue
                    return ("⚠️ *Engine Timeout:*\nProses eksekusi melebihi batas waktu 3 menit. Silakan ulangi perintah Tuan All.", None)

                out_text = stdout.decode("utf-8", errors="replace").strip()
                err_text = stderr.decode("utf-8", errors="replace").strip()

                if not out_text:
                    logger.error(f"AGY process returned empty stdout. stderr: {err_text}")
                    if attempt < max_retries:
                        await asyncio.sleep(2.0)
                        continue
                    return (err_text if err_text else "⚠️ Tidak ada output yang dikembalikan oleh engine.", None)

                try:
                    data = json.loads(out_text)
                except json.JSONDecodeError:
                    start_brace = out_text.find("{")
                    end_brace = out_text.rfind("}")
                    if start_brace != -1 and end_brace > start_brace:
                        data = json.loads(out_text[start_brace:end_brace+1])
                    else:
                        raise

                status = str(data.get("status", "")).upper()
                if status == "ERROR" or ("error" in data and data["error"]):
                    err_msg = data.get("error") or "Terjadi kesalahan internal pada engine AGY."
                    last_err_msg = err_msg
                    last_error_data = data
                    logger.error(f"AGY Engine Error (Attempt {attempt+1}/{max_retries+1}): {err_msg}")
                    
                    is_retryable_error = any(kw in err_msg.lower() for kw in [
                        "network issue", "connecting to the server", "connection reset", "eof", "timed out",
                        "stream was interrupted", "stream interrupted", "interrupted", "server restart", "socket",
                        "wsarecv", "wsasend", "forcibly closed"
                    ])
                    if is_retryable_error and attempt < max_retries:
                        logger.info(f"Transient stream/network glitch detected ('{err_msg}'). Retrying in 2.5s (Attempt {attempt+2}/{max_retries+1})...")
                        # If a specific session repeatedly gets stream interruption, fall back to clean session on retry
                        if "interrupted" in err_msg.lower() and attempt >= 1 and target_conv_id:
                            logger.warning(f"Session {target_conv_id} repeatedly suffered stream interruption. Falling back to clean isolated session.")
                            if "--conversation" in cmd:
                                c_idx = cmd.index("--conversation")
                                cmd.pop(c_idx)
                                cmd.pop(c_idx)
                            target_conv_id = None
                        await asyncio.sleep(2.5)
                        continue
                    
                    if is_retryable_error:
                        record_task_end("Server Google Antigravity mengalami pemutusan stream/koneksi sementara.", success=False)
                        return ("⚠️ *Koneksi Terganggu:*\nServer Google Antigravity mengalami pemutusan stream/koneksi sementara. Silakan kirim ulang pesan Tuan All.", data)
                    record_task_end(err_msg, success=False)
                    return (f"⚠️ *Engine Error:*\n`{err_msg}`", data)

                resp_text = data.get("response", "").strip()
                conv_id = data.get("conversation_id")
                usage = data.get("usage", {})
                duration = data.get("duration_seconds", 0.0)
                num_turns = data.get("num_turns", session.turns + 1)
                
                session.update_usage(conv_id, usage, duration, num_turns)
                if conv_id:
                    session.telegram_conv_id = conv_id
                    session.save_session()
                record_task_end(response_summary=resp_text, success=True)
                return (resp_text if resp_text else "✅ (Eksekusi selesai tanpa output teks balasan)", data)

            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from AGY output: {out_text[:300]}")
                if attempt < max_retries:
                    await asyncio.sleep(2.0)
                    continue
                record_task_end(out_text or err_text, success=False)
                return (out_text if out_text else err_text, None)
            except Exception as ex:
                logger.error(f"Exception during AGY turn execution (Attempt {attempt+1}): {ex}")
                if attempt < max_retries:
                    await asyncio.sleep(2.0)
                    continue
                record_task_end(str(ex), success=False)
                return (f"⚠️ *Engine Exception:*\n`{str(ex)}`", None)

        record_task_end(last_err_msg, success=False)
        return (f"⚠️ *Engine Error:*\n`{last_err_msg}`", last_error_data)
    finally:
        is_turn_in_progress = False
        current_running_task_desc = ""
        current_task_start_time = 0.0

# --- HELPER FUNCTIONS ---
def is_authorized(update: Update) -> bool:
    user = update.effective_user
    if user and user.id == AUTHORIZED_USER_ID:
        return True
    logger.warning(f"Unauthorized access attempt by user_id: {user.id if user else 'Unknown'}")
    return False

def format_progress_bar(used: int, total: int, width: int = 34) -> str:
    fraction = min(1.0, max(0.0, used / total)) if total > 0 else 0.0
    filled = int(fraction * width)
    empty = width - filled
    pct = fraction * 100
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {pct:.2f}%"

def format_bytes(bytes_val: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"

async def send_continuous_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        except Exception:
            pass
        await asyncio.sleep(4.0)

def check_approval_request(text: str) -> Optional[InlineKeyboardMarkup]:
    """
    Checks if the AI response text is asking for user approval, confirmation, or authorization.
    If yes, returns an InlineKeyboardMarkup with interactive buttons [Setujui & Lanjutkan] and [Batalkan].
    """
    if not text:
        return None
    clean_text = re.sub(r'```[\s\S]*?```', '', text)
    pattern = r'(?:\b(?:apakah\s+(?:tuan\s+all\s+)?(?:setuju|menyetujui)|butuh\s+persetujuan|mohon\s+konfirmasi|konfirmasi\s+persetujuan|apakah\s+ingin\s+melanjutkan|apakah\s+boleh|setujui\s+tindakan\s+ini|apakah\s+anda\s+yakin|apakah\s+tuan\s+yakin|mohon\s+persetujuannya|persetujuan\s+tuan\s+all)\b|\[(?:PERMINTAAN\s+PERSETUJUAN|NEED_APPROVAL)\])'
    if re.search(pattern, clean_text, re.IGNORECASE):
        keyboard = [
            [
                InlineKeyboardButton("✅ Setujui & Lanjutkan", callback_data="approval_confirm"),
                InlineKeyboardButton("❌ Batalkan Tindakan", callback_data="approval_cancel"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    return None

def markdown_to_telegram_html(md: str) -> str:
    """
    Converts standard markdown from AI responses into clean, valid Telegram HTML.
    Supports:
    - Native Telegram blockquotes (<blockquote>...</blockquote>) for lines starting with '>'
    - Bold (<b>...</b>) for **text** or __text__
    - Italic (<i>...</i>) for *text* or _text_
    - Monospace inline code (<code>...</code>) for `code`
    - Code blocks (<pre><code class="language-xyz">...</code></pre>) for ```lang ... ```
    - Markdown links (<a href="...">...</a>) for [text](url)
    - Clean bullet points (•)
    Eliminates raw '>' or '**' characters and renders authentic Telegram rich styling.
    """
    if not md:
        return ""

    # 1. Protect code blocks
    code_blocks = []
    def save_code_block(m):
        lang = m.group(1) or ""
        code = html.escape(m.group(2).rstrip())
        idx = len(code_blocks)
        if lang:
            code_blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        else:
            code_blocks.append(f'<pre><code>{code}</code></pre>')
        return f"___CODE_BLOCK_{idx}___"

    # 2. Protect inline code
    inline_codes = []
    def save_inline_code(m):
        idx = len(inline_codes)
        inline_codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"___INLINE_CODE_{idx}___"

    text = re.sub(r'```([a-zA-Z0-9_\-]+)?\r?\n([\s\S]*?)```', save_code_block, md)
    text = re.sub(r'`([^`\r\n]+)`', save_inline_code, text)

    # 3. Handle blockquotes (> line)
    lines = text.split("\n")
    processed_lines = []
    in_quote = False
    quote_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            q_content = re.sub(r'^>\s?', '', line)
            quote_lines.append(q_content)
            in_quote = True
        else:
            if in_quote:
                inner = "\n".join(quote_lines).strip()
                processed_lines.append(f"<blockquote>{inner}</blockquote>")
                quote_lines = []
                in_quote = False
            processed_lines.append(line)
    if in_quote:
        inner = "\n".join(quote_lines).strip()
        processed_lines.append(f"<blockquote>{inner}</blockquote>")

    text = "\n".join(processed_lines)

    # 4. Escape remaining HTML and parse Markdown styling
    parts = re.split(r'(</?blockquote>|___CODE_BLOCK_\d+___|___INLINE_CODE_\d+___)', text)
    escaped_parts = []
    for part in parts:
        if part.startswith("<blockquote") or part == "</blockquote>" or part.startswith("___CODE_BLOCK_") or part.startswith("___INLINE_CODE_"):
            escaped_parts.append(part)
        else:
            p = html.escape(part)
            # Bold: **text** or __text__
            p = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', p)
            p = re.sub(r'__(.+?)__', r'<b>\1</b>', p)
            # Italic: *text* or _text_
            p = re.sub(r'(?<!\w)\*([^*\n]+?)\*(?!\w)', r'<i>\1</i>', p)
            p = re.sub(r'(?<!\w)_([^_\n]+?)_(?!\w)', r'<i>\1</i>', p)
            # Strikethrough: ~~text~~
            p = re.sub(r'~~(.+?)~~', r'<s>\1</s>', p)
            # Markdown links: [text](url)
            p = re.sub(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', r'<a href="\2">\1</a>', p)
            # Clean headers: # Header -> <b>Header</b>
            p = re.sub(r'^(?:#{1,6})\s+(.+)$', r'<b>\1</b>', p, flags=re.MULTILINE)
            # Clean bullet points: - item or * item -> • item
            p = re.sub(r'^[ \t]*[*\-][ \t]+', '• ', p, flags=re.MULTILINE)
            # Clean excessive divider lines
            p = re.sub(r'^[ \t]*[-*_]{3,}[ \t]*$', '──────────', p, flags=re.MULTILINE)
            escaped_parts.append(p)

    res = "".join(escaped_parts)

    # 5. Restore protected code blocks
    for idx, cb in enumerate(code_blocks):
        res = res.replace(f"___CODE_BLOCK_{idx}___", cb)
    for idx, ic in enumerate(inline_codes):
        res = res.replace(f"___INLINE_CODE_{idx}___", ic)

    return res

async def send_chunked_message(update: Update, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[InlineKeyboardMarkup] = None):
    if reply_markup is None:
        reply_markup = check_approval_request(text)

    # Automatically transform standard markdown into clean, valid Telegram HTML
    formatted_html = None
    try:
        formatted_html = markdown_to_telegram_html(text)
    except Exception as conv_err:
        logger.warning(f"Markdown to HTML conversion error: {conv_err}")
        formatted_html = None

    text_to_send = formatted_html if formatted_html else text
    active_parse_mode = constants.ParseMode.HTML if formatted_html else None

    max_len = 4000
    if len(text_to_send) <= max_len:
        try:
            await update.effective_message.reply_text(text_to_send, parse_mode=active_parse_mode, reply_markup=reply_markup)
            return
        except Exception as e:
            logger.warning(f"HTML send error: {e}, falling back to plain text.")
            clean_plain = re.sub(r'<[^>]+>', '', text_to_send)
            await update.effective_message.reply_text(clean_plain if clean_plain.strip() else text, reply_markup=reply_markup)
            return

    parts = []
    curr = text_to_send
    while curr:
        if len(curr) <= max_len:
            parts.append(curr)
            break
        split_idx = curr.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = curr.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        parts.append(curr[:split_idx])
        curr = curr[split_idx:].lstrip()

    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        try:
            await update.effective_message.reply_text(part, parse_mode=active_parse_mode, reply_markup=markup)
        except Exception:
            clean_part = re.sub(r'<[^>]+>', '', part)
            await update.effective_message.reply_text(clean_part if clean_part.strip() else part, reply_markup=markup)
        await asyncio.sleep(0.3)

async def auto_dispatch_files_from_response(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    Scans the AI response text for referenced local files or images (e.g. from Downloads, Workspace,
    file:// links, markdown ![alt](path) or [name](path), or Windows absolute paths),
    and automatically dispatches them directly as Telegram photos or documents to the chat.
    Ensures that when Tuan All requests any file/image from the AI agent, it is delivered directly
    in chat rather than as an artifact or plain path string.
    """
    if not text or not update or not update.effective_chat:
        return

    import urllib.parse
    chat_id = update.effective_chat.id
    candidates = []

    # 1. Markdown image syntax: ![alt](path)
    for m in re.finditer(r'!\[.*?\]\((.+?)\)', text):
        candidates.append(m.group(1).strip())

    # 2. Markdown link syntax: [title](path)
    for m in re.finditer(r'\[.*?\]\((.+?)\)', text):
        candidates.append(m.group(1).strip())

    # 3. Explicit file:/// URIs (supporting spaces and quotes)
    for m in re.finditer(r'file:///([^\r\n\)\>"`\']+?\.[a-zA-Z0-9]{2,5})', text):
        candidates.append("file:///" + m.group(1).strip())

    # 4. Explicit Windows file paths (supporting spaces, backticks, quotes, and both \ and / slashes)
    for m in re.finditer(r'([a-zA-Z]:[\\/][^\r\n`"<>|\*]+?\.[a-zA-Z0-9]{2,5})', text):
        candidates.append(m.group(1).strip())

    sent_canonical_paths = set()
    files_to_send = []

    for raw in candidates:
        clean = raw.strip().strip('"\'`')
        if clean.startswith("file:///"):
            clean = clean[8:]
        elif clean.startswith("file://"):
            clean = clean[7:]

        clean = urllib.parse.unquote(clean)
        clean = clean.replace('/', '\\')
        clean = re.sub(r'[\)\]\>\*`"\']+$', '', clean).strip()

        if not clean or len(clean) < 3:
            continue

        p = Path(clean)
        if not p.is_absolute():
            for base in [DOWNLOADS_DIR, WORKSPACE_DIR, BRIDGE_DIR, Path.home() / "Downloads"]:
                cand = base / clean
                if cand.exists() and cand.is_file():
                    p = cand
                    break

        try:
            if p.exists() and p.is_file():
                canon = str(p.resolve()).lower()
                # Ignore git, cache, log, or script internals
                if any(ign in canon for ign in [r'\.git\\', r'__pycache__', r'\node_modules\\', r'bridge_telegram.log', r'allzxy_bot.log', r'active_session.json', r'quota_state.json']):
                    continue
                # Ignore brain artifact markdown files
                if canon.endswith('.md') and r'\.gemini\antigravity-cli\brain' in canon:
                    continue

                if canon not in sent_canonical_paths:
                    sent_canonical_paths.add(canon)
                    files_to_send.append(p)
                    if len(files_to_send) >= 10:
                        break
        except Exception:
            pass

    if files_to_send:
        logger.info(f"auto_dispatch: Found {len(candidates)} candidate strings, dispatching {len(files_to_send)} file(s): {[f.name for f in files_to_send]}")

    for p in files_to_send:
        try:
            size_bytes = p.stat().st_size
            if size_bytes == 0 or size_bytes > 50 * 1024 * 1024:
                continue

            size_str = format_bytes(size_bytes)
            # Use plain text caption to prevent Markdown parse error with underscores in filenames!
            caption = f"📄 {p.name} ({size_str})"
            suffix = p.suffix.lower()

            with open(p, "rb") as f:
                if suffix in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
                    try:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=f,
                            caption=caption,
                            parse_mode=None
                        )
                        logger.info(f"auto_dispatch: Successfully sent photo {p.name}")
                        continue
                    except Exception as pe:
                        logger.warning(f"Failed to send {p.name} as photo: {pe}, falling back to document.")
                        f.seek(0)

                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=p.name,
                    caption=caption,
                    parse_mode=None
                )
                logger.info(f"auto_dispatch: Successfully sent document {p.name}")
            await asyncio.sleep(0.3)
        except Exception as fe:
            logger.error(f"Error auto-dispatching file {p}: {fe}")

# --- COMMAND HANDLERS ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    msg = (
        "🤖 *Bridge-Telegram — Connected*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot Telegram terhubung langsung ke engine *{BACKEND_PROVIDER}*.\n\n"
        f"👤 *Account*: `{USER_ACCOUNT_EMAIL or 'Default'}`\n"
        f"🤖 *Active Model*: `{session.active_model}`\n"
        f"🆔 *Live Conversation*: `{session.conversation_id or 'Baru (Sesi Siap)'}`\n"
        f"📂 *Workspace*: `{WORKSPACE_DIR}`\n\n"
        "💡 *Tips Cepat*:\n"
        "• `/backend` — Cek atau ganti engine provider (Antigravity, OpenAI, 9Router, Hermes, CLI)\n"
        "• `/model` — Ganti model LLM secara instan\n"
        "• `/status` — Cek status server, resource, dan koneksi engine\n"
        "• `/usage` — Cek token realtime\n"
        "• Kirim teks, gambar, atau berkas kode langsung untuk dieksekusi!"
    )
    await update.effective_message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    msg = (
        "📋 *Bridge-Telegram Command Suite*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚙️ *Engine & Sesi Real-Time*:\n"
        "• `/backend` `[nama_provider]` — Cek atau ganti provider AI (antigravity, openai, 9router, hermes, cli_agent).\n"
        "• `/model` `[nama/alias]` — Lihat daftar model resmi atau ganti model aktif.\n"
        "• `/status` — Status server hardware, OS, disk, memori, dan binary engine.\n"
        "• `/sync` `[id]` — Sinkronkan Telegram ke sesi kerja CLI di server.\n"
        "• `/sessions` — Daftar riwayat sesi percakapan CLI yang ada di server.\n"
        "• `/autosync` `[on|off]` — Kontrol sinkronisasi otomatis saat terminal CLI ditutup.\n"
        "• `/usage` — Statistik penggunaan token realtime.\n"
        "• `/quota` — Status kuota akun mingguan/5 jam.\n"
        "• `/clear` atau `/reset` — Buat sesi percakapan baru di engine.\n"
        "• `/restart` — Merestart bridge service secara otonom.\n"
        "• `/exit` — Menghentikan service bot.\n\n"
        "📁 *Transfer & Pengelolaan Berkas (PC ⇄ Telegram)*:\n"
        "• `/get` `<path>` — Ambil berkas dari PC dan kirimkan ke chat Telegram (contoh: `/get bridge_telegram.py`).\n"
        "• `/download` `<url> [path]` — Unduh berkas dari link web langsung ke harddisk PC.\n"
        "• *Kirim Berkas ke Bot* — Kirim dokumen/foto apa saja, bot otomatis menyimpannya ke PC (opsional caption: `simpan di <path>`).\n"
        "• *Natural Chat* — Bisa ketik langsung: `kirim file <path>` atau `download <url>`.\n\n"
        "🚀 *Mode Agentic & Workflow*:\n"
        "• `/plan` `<tugas>` — Mode perencanaan arsitektur via engine Antigravity.\n"
        "• `/goal` `<target>` — Mode eksekusi mandiri kontinu hingga selesai.\n"
        "• `/boost` `<tugas>` — Mode penalaran mendalam (*deep thinking*).\n"
        "• `/browser` `<query/url>` — Mode penelusuran web terarah.\n"
        "• `/grillme` `<topik>` — Mode interview penajaman keputusan arsitektur.\n"
        "• `/teamwork` `<tugas>` — Mode kolaborasi multi-agent otonom.\n"
        "• `/humanize` `<teks>` — Menulis ulang teks agar terdengar natural manusia (blader/humanizer).\n"
        "• `/learn` `<aturan>` — Simpan preferensi permanen ke `AGENTS.md`.\n"
        "• `/schedule` `<detik>` `<pesan>` — Timer notifikasi pengingat.\n\n"
        "💬 *Multi-Modal Execution*:\n"
        "• Kirim teks langsung untuk instruksi coding.\n"
        "• Kirim gambar / screenshot untuk analisa visual atau penyimpanan.\n"
        "• Kirim dokumen / source file untuk analisa berkas atau penyimpanan."
    )
    await send_chunked_message(update, msg, parse_mode=constants.ParseMode.MARKDOWN)

_last_live_usage_cache = {}
_last_live_usage_time = 0.0

async def fetch_live_agy_usage(force: bool = False) -> dict:
    """
    Fetches the true, live model quota and usage breakdown directly from agy.exe -p /usage.
    Synchronizes 100% with the desktop CLI rate limit buckets (Gemini, Claude, GPT).
    Caches for 20 seconds to prevent unnecessary engine spawn on rapid calls.
    """
    global _last_live_usage_cache, _last_live_usage_time
    now = time.time()
    if not force and _last_live_usage_cache and (now - _last_live_usage_time < 20.0):
        return _last_live_usage_cache

    cmd = [
        str(AGY_EXE),
        "-p", "/usage",
        "--output-format", "json"
    ]
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKSPACE_DIR),
            **kwargs
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        out_text = stdout.decode("utf-8", errors="replace").strip()
        data = json.loads(out_text)
        command_data = data.get("command", {}).get("data", {})
        groups = command_data.get("groups", [])
        
        parsed = {
            "groups": groups,
            "raw_response": data.get("response", ""),
            "success": True
        }
        _last_live_usage_cache = parsed
        _last_live_usage_time = now

        # Update quota_state.json with live fresh data for compatibility
        try:
            gemini_group = next((g for g in groups if "Gemini" in g.get("name", "")), None)
            if gemini_group:
                w_b = next((b for b in gemini_group.get("buckets", []) if b.get("window") == "weekly"), {})
                f_b = next((b for b in gemini_group.get("buckets", []) if b.get("window") == "5h"), {})
                q_data = {
                    "account": USER_ACCOUNT_EMAIL,
                    "weekly_pct": round(w_b.get("remaining_fraction", 0.0) * 100, 2),
                    "weekly_time_str": w_b.get("description", "").split("refresh in ")[-1].rstrip(".") if "refresh in " in w_b.get("description", "") else w_b.get("reset_time", "-"),
                    "five_h_pct": round(f_b.get("remaining_fraction", 0.0) * 100, 2),
                    "five_h_time_str": f_b.get("description", "").split("refresh in ")[-1].rstrip(".") if "refresh in " in f_b.get("description", "") else f_b.get("reset_time", "-"),
                    "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(QUOTA_FILE, "w", encoding="utf-8") as qf:
                    json.dump(q_data, qf, indent=2)
        except Exception as qe:
            logger.warning(f"Error persisting quota_state.json: {qe}")

        return parsed
    except Exception as e:
        logger.error(f"Error fetching live agy usage: {e}")
        return {"groups": [], "success": False, "error": str(e)}

async def usage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    live_data = await fetch_live_agy_usage()
    groups = live_data.get("groups", [])
    
    quota_blocks = []
    for g in groups:
        g_name = g.get("name", "Model Group")
        b_lines = []
        for b in g.get("buckets", []):
            b_name = b.get("name", "Limit")
            rem_pct = b.get("remaining_fraction", 0.0) * 100
            bar = format_progress_bar(int(rem_pct), 100, width=16)
            desc = b.get("description", "")
            refresh_note = ""
            if "refresh in " in desc:
                refresh_note = f"\n  ⏱️ Refresh: _{desc.split('refresh in ')[-1].rstrip('.')}_"
            elif b.get("reset_time"):
                refresh_note = f"\n  ⏱️ Reset: `{b.get('reset_time')}`"
                
            b_lines.append(
                f"• *{b_name}*: `{rem_pct:.1f}%` tersisa\n"
                f"  `{bar}`{refresh_note}"
            )
        quota_blocks.append(f"🌐 *{g_name}*:\n" + "\n".join(b_lines))

    quota_section = "\n\n".join(quota_blocks) if quota_blocks else "⚠️ _Tidak dapat membaca live quota engine._"

    curr_tokens = session.last_total_tokens
    cumul_tokens = session.cumulative_total_tokens
    limit = session.context_window_limit
    ctx_bar = format_progress_bar(curr_tokens, limit, width=18)
    conv_display = session.conversation_id or "Belum ada sesi"

    usage_text = (
        "📊 *Antigravity Engine Realtime Usage (Live Desktop Synced)*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Akun*: `{USER_ACCOUNT_EMAIL}`\n"
        f"🤖 *Model Aktif*: `{session.active_model}`\n"
        f"🆔 *Conversation ID*: `{conv_display}`\n\n"
        f"{quota_section}\n\n"
        "📈 *Konteks & Sesi Kerja Terakhir*:\n"
        f"• *Context Window*: `{curr_tokens:,}` / `{limit:,}` tokens\n"
        f"  `{ctx_bar}`\n"
        f"• *Turn Total Terakhir*: `{session.last_total_tokens:,}` tokens "
        f"(Prompt: `{session.last_input_tokens:,}`, Output: `{session.last_output_tokens:,}`, Latency: `{session.last_duration:.2f}s`)\n"
        f"• *Total Sesi*: `{session.turns}` turns | Kumulatif: `{cumul_tokens:,}` tokens\n\n"
        "🟢 *Status*: `100% Identik & Terhubung Langsung ke Google Backend Desktop`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await send_chunked_message(update, usage_text, parse_mode=constants.ParseMode.MARKDOWN)

async def quota_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    if not QUOTA_FILE.exists():
        await update.effective_message.reply_text("⚠️ Data `quota_state.json` belum tersedia di folder bridge.")
        return
    
    try:
        with open(QUOTA_FILE, "r", encoding="utf-8-sig") as f:
            q = json.load(f)
        
        w_pct = q.get("weekly_pct", 0.0)
        w_time = q.get("weekly_time_str", "-")
        f_pct = q.get("five_h_pct", 0.0)
        f_time = q.get("five_h_time_str", "-")
        acc = q.get("account", USER_ACCOUNT_EMAIL)
        
        w_bar = format_progress_bar(int(w_pct), 100, width=18)
        f_bar = format_progress_bar(int(f_pct), 100, width=18)
        
        msg = (
            "⚡ *Quota & Usage Status*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Akun*: `{acc}`\n\n"
            f"⏳ *5-Hour Rolling Quota*:\n"
            f"• Kapasitas Tersisa: `{f_pct:.1f}%`\n"
            f"• Progress: `{f_bar}`\n"
            f"• Reset Dalam: `{f_time}`\n\n"
            f"📅 *Weekly Account Quota*:\n"
            f"• Kapasitas Tersisa: `{w_pct:.1f}%`\n"
            f"• Progress: `{w_bar}`\n"
            f"• Reset Dalam: `{w_time}`\n\n"
            f"🟢 *Engine Backend*: `{BACKEND_PROVIDER}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.effective_message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Gagal membaca quota: `{e}`")

async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    args = context.args
    if not args:
        session.sync_model_from_settings()
        lines = []
        for key, name in OFFICIAL_MODELS.items():
            is_cur = " 👈 [AKTIF]" if name.lower() == session.active_model.lower() else ""
            lines.append(f"• `{name}`{is_cur}")
        
        models_text = "\n".join(lines)
        msg = (
            "🧠 *Models Engine (2-Way Synchronized)*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Model Aktif Saat Ini*: `{session.active_model}`\n\n"
            f"📦 *Daftar Model Tersedia*:\n{models_text}\n\n"
            "💡 *Shortcut Praktis*:\n"
            "• `/model 3.8` — Gemini 3.8 Flash (High)\n"
            "• `/model 3.8 med` — Gemini 3.8 Flash (Medium)\n"
            "• `/model pro` — Gemini 3.1 Pro (High)\n"
            "• `/model sonnet` — Claude Sonnet 4.6 (Thinking)\n"
            "• `/model opus` — Claude Opus 4.6 (Thinking)\n"
            "• `/model gpt` — GPT-OSS 120B (Medium)"
        )
        await send_chunked_message(update, msg, parse_mode=constants.ParseMode.MARKDOWN)
        return

    raw_arg = " ".join(args).strip()
    lookup = raw_arg.lower().replace(" ", "-")
    
    resolved_model = MODEL_SHORTCUTS.get(lookup) or MODEL_SHORTCUTS.get(raw_arg.lower())
    if not resolved_model:
        for k, v in OFFICIAL_MODELS.items():
            if raw_arg.lower() in k.lower() or raw_arg.lower() in v.lower():
                resolved_model = v
                break
    
    new_model = resolved_model if resolved_model else raw_arg
    session.update_model_to_settings(new_model)

    await update.effective_message.reply_text(
        f"✅ *Model Berhasil Diubah!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 *Model Baru*: `{new_model}`\n\n"
        "🔄 *Sinkronisasi 2-Arah Aktif*: Pengaturan ini otomatis tersimpan ke `settings.json` dan langsung aktif di terminal PC (CLI) maupun chat Telegram.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    cpu_usage = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(WORKSPACE_DIR))
    
    adapter = get_active_adapter()
    adapter_status = await adapter.get_status()
    
    msg = (
        "🖥️ *Bridge-Telegram & Engine Status*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 *Gateway State*: `Bridge-Telegram (Online)`\n"
        f"⚡ *Active Provider*: `{BACKEND_PROVIDER}` ({adapter_status.get('name')})\n"
        f"🧠 *Active Model*: `{session.active_model}`\n"
        f"🆔 *Active Conversation*: `{session.conversation_id or 'None'}`\n"
        f"💻 *Host OS*: `{platform.system()} {platform.release()} ({platform.machine()})`\n"
        f"⚡ *CPU Usage*: `{cpu_usage}%`\n"
        f"💾 *Memory (RAM)*: `{mem.percent}% used` (`{format_bytes(mem.used)}` / `{format_bytes(mem.total)}`)\n"
        f"💽 *Disk Space*: `{disk.percent}% used` (`{format_bytes(disk.free)}` Free)\n"
        f"📂 *Workspace*: `{session.working_dir}`\n\n"
        "🟢 *Engine Integration*: `Adaptive Multi-Provider Gateway`"
    )
    await update.effective_message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)

async def cd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    if not context.args:
        cur = session.working_dir
        items = list(cur.iterdir())[:15] if cur.exists() else []
        item_lines = "\n".join([f"• `{it.name}`" + ("/" if it.is_dir() else "") for it in items])
        await update.effective_message.reply_text(
            f"📂 *Active Workspace Directory*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 `{cur}`\n\n"
            f"📁 *Isi Folder*:\n{item_lines or '(Folder kosong)'}\n\n"
            f"💡 Ganti folder: `/cd <path>` (contoh: `/cd E:\\Alfan\\telegram-bridge`)",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
        
    raw_path = " ".join(context.args).strip().strip('"\'')
    new_dir = Path(raw_path)
    if not new_dir.is_absolute():
        new_dir = (session.working_dir / raw_path).resolve()
        
    if not new_dir.exists():
        await update.effective_message.reply_text(f"❌ Folder tidak ditemukan di PC:\n`{new_dir}`", parse_mode=constants.ParseMode.MARKDOWN)
        return
        
    if not new_dir.is_dir():
        await update.effective_message.reply_text(f"⚠️ `{new_dir}` adalah berkas, bukan folder.", parse_mode=constants.ParseMode.MARKDOWN)
        return
        
    session.working_dir = new_dir
    session.save_session()
    
    items = list(new_dir.iterdir())[:10]
    item_lines = "\n".join([f"• `{it.name}`" + ("/" if it.is_dir() else "") for it in items])
    await update.effective_message.reply_text(
        f"✅ *Workspace Berhasil Dialihkan!*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *Direktori Aktif*: `{new_dir}`\n\n"
        f"📁 *Daftar Isi*:\n{item_lines or '(Folder kosong)'}\n\n"
        "Semua instruksi coding, shell `!`, dan operasi AI akan dieksekusi di folder ini.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def ls_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    target_dir = session.working_dir
    if context.args:
        raw_p = " ".join(context.args).strip().strip('"\'')
        p = Path(raw_p)
        if not p.is_absolute():
            p = (session.working_dir / raw_p).resolve()
        if p.exists() and p.is_dir():
            target_dir = p
            
    if not target_dir.exists():
        await update.effective_message.reply_text(f"❌ Direktori `{target_dir}` tidak ditemukan.")
        return
        
    try:
        items = sorted(list(target_dir.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for it in items[:40]:
            if it.is_dir():
                lines.append(f"📁 `{it.name}/`")
            else:
                lines.append(f"📄 `{it.name}` ({format_bytes(it.stat().st_size)})")
        total_count = len(items)
        more_str = f"\n_...dan {total_count - 40} item lainnya_" if total_count > 40 else ""
        text = (
            f"📂 *Daftar Berkas: `{target_dir}`*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total: {total_count} item\n\n" + "\n".join(lines) + more_str
        )
        await send_chunked_message(update, text, parse_mode=constants.ParseMode.MARKDOWN)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error membaca direktori: `{e}`")

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    prev_id = session.conversation_id
    prev_turns = session.turns
    session.reset_session()
    
    msg = (
        "🧹 *Sesi Percakapan Direset*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Sesi Sebelumnya: `{prev_id}` ({prev_turns} turns)\n"
        "• Sesi Baru: `Fresh Conversation Initialized`\n\n"
        "Siap menerima instruksi baru, *Tuan All*."
    )
    await update.effective_message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)

async def backend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    global BACKEND_PROVIDER
    args = context.args
    if not args:
        adapter = get_active_adapter()
        status = await adapter.get_status()
        msg = (
            "🔌 *Universal AI Engine & Backend Provider*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Provider Aktif*: `{BACKEND_PROVIDER}`\n"
            f"⚡ *Nama Engine*: `{status.get('name')}`\n"
            f"📦 *Tipe*: `{status.get('type')}`\n\n"
            "🌐 *Pilihan Provider Tersedia*:\n"
            "• `antigravity` — Google Antigravity CLI binary\n"
            "• `openai_compatible` — API OpenAI/vLLM/Ollama\n"
            "• `nine_router` — 9Router Multi-LLM Gateway\n"
            "• `hermes` — Hermes Agent / Local Ollama\n"
            "• `cli_agent` — External Subprocess CLI Agent\n\n"
            "💡 *Cara Mengganti Provider*:\n"
            "Ketik: `/backend <nama_provider>`\n"
            "Contoh: `/backend 9router` atau `/backend antigravity`"
        )
        await send_chunked_message(update, msg, parse_mode=constants.ParseMode.MARKDOWN)
        return

    new_prov = args[0].lower().strip()
    if new_prov == "auto":
        detected_p, reason = auto_detect_engine(_cfg)
        BACKEND_PROVIDER = detected_p
        _cfg["backend_provider"] = "auto"
        config_mgr.save(_cfg)
        await update.effective_message.reply_text(
            f"🔄 *Auto-Detection Engine Aktif!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Engine Terdeteksi*: `{detected_p}`\n"
            f"💡 *Keterangan*: {reason}\n\n"
            "Sistem otomatis mendeteksi dan beradaptasi dengan environment host.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    valid_map = {
        "antigravity": "antigravity",
        "agy": "antigravity",
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "9router": "nine_router",
        "nine_router": "nine_router",
        "hermes": "hermes",
        "cli": "cli_agent",
        "cli_agent": "cli_agent",
        "opencode": "cli_agent",
    }
    if new_prov not in valid_map:
        await update.effective_message.reply_text(
            f"❌ Provider `{new_prov}` tidak dikenali.\nPilihan: `auto`, `antigravity`, `openai`, `9router`, `hermes`, `cli_agent`"
        )
        return

    canonical_prov = valid_map[new_prov]
    BACKEND_PROVIDER = canonical_prov
    _cfg["backend_provider"] = canonical_prov
    config_mgr.save(_cfg)

    await update.effective_message.reply_text(
        f"✅ *Backend Provider Berhasil Diubah!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Provider Baru*: `{canonical_prov}`\n\n"
        "Konfigurasi telah diperbarui di `config.json` dan aktif seketika.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    task = " ".join(context.args) if context.args else "Rancang arsitektur modul baru"
    prompt = f"/plan {task}"
    
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"🗺️ *[Antigravity Planning Blueprint]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def goal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    task = " ".join(context.args) if context.args else "Tuntaskan implementasi target mandiri"
    prompt = f"/goal {task}"
    
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"🎯 *[Antigravity Autonomous Goal Result]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def boost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    task = " ".join(context.args) if context.args else "Deep reasoning analysis"
    prompt = f"/boost {task}"
    
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"🚀 *[Antigravity Deep Boost Analysis]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def browser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    query = " ".join(context.args) if context.args else "Riset dokumentasi AI agent terbaru"
    prompt = f"/browser {query}"
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"🌐 *[Antigravity Browser Agent]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def grillme_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    task = " ".join(context.args) if context.args else "Analisa keputusan desain arsitektur"
    prompt = f"/grill-me {task}"
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"🎯 *[Antigravity Interactive Alignment]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def teamwork_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    task = " ".join(context.args) if context.args else "Koordinasikan multi-agent task"
    prompt = f"/teamwork-preview {task}"
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"👥 *[Antigravity Teamwork Multi-Agent]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def humanize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    text_to_humanize = " ".join(context.args) if context.args else ""
    if not text_to_humanize:
        await update.effective_message.reply_text("Format: `/humanize <teks yang ingin di-humanize>`\nAtau balas/reply pesan dengan `/humanize`")
        return
    
    prompt = f"Gunakan skill humanizer (blader/humanizer) untuk menulis ulang teks berikut agar terdengar natural, mengalir layaknya tulisan manusia, dan bebas dari pola artifisial AI:\n\n{text_to_humanize}"
    chat_id = update.effective_chat.id
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, f"✍️ *[Humanized Prose]*\n\n{resp}", parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        await update.effective_message.reply_text(f"❌ Error: `{e}`")

async def learn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    rule = " ".join(context.args)
    if not rule:
        await update.effective_message.reply_text("Format: `/learn <aturan/preferensi>`")
        return
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n- [{timestamp}] {rule}"
    
    for fpath in [AGENTS_MD, GEMINI_MD]:
        if fpath.exists():
            try:
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(entry)
            except Exception as e:
                logger.error(f"Error writing {fpath}: {e}")

    await update.effective_message.reply_text(
        f"🧠 *Aturan Berhasil Disimpan Permanen*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📝 `{rule}`\n📂 Tersimpan di `AGENTS.md` & `GEMINI.md`",
        parse_mode=constants.ParseMode.MARKDOWN,
    )

async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    args = context.args
    if not args or len(args) < 2:
        await update.effective_message.reply_text("Format: `/schedule <detik> <pesan pengingat>`")
        return

    try:
        seconds = int(args[0])
        reminder_msg = " ".join(args[1:])
    except ValueError:
        seconds = 30
        reminder_msg = " ".join(args)

    async def _timer_callback():
        await asyncio.sleep(seconds)
        try:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=f"🔔 *[SCHEDULED NOTIFICATION]*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📌 `{reminder_msg}`\n⏱️ `{datetime.datetime.now().strftime('%H:%M:%S')}`",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Error in timer callback: {e}")

    asyncio.create_task(_timer_callback())
    await update.effective_message.reply_text(
        f"✅ Jadwal pengingat aktif untuk `{seconds}` detik ke depan: \"{reminder_msg}\"",
        parse_mode=constants.ParseMode.MARKDOWN,
    )

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    logger.info(f"restart_cmd triggered by user {update.effective_user.id}")
    await update.effective_message.reply_text("🔄 *Merestart Bridge-Telegram Service...*", parse_mode=constants.ParseMode.MARKDOWN)
    vbs_script = BRIDGE_DIR / "Auto Run" / "start_bot_hidden.vbs"
    if vbs_script.exists():
        subprocess.Popen(["wscript.exe", str(vbs_script)], cwd=str(BRIDGE_DIR))
    else:
        subprocess.Popen([sys.executable, str(BRIDGE_DIR / "bridge_telegram.py")], cwd=str(BRIDGE_DIR))
    os._exit(0)

async def exit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    logger.info(f"exit_cmd triggered by user {update.effective_user.id}")
    protect_and_restore_auth_vault()
    msg = (
        "🟢 *Bridge-Telegram Siap Siaga!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🖥️ *Status*: Sesi dan bot tetap siaga di background.\n\n"
        "💡 _Anda dapat langsung mengetik instruksi kapan saja dari Telegram._"
    )
    await update.effective_message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN)

async def stopbot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    logger.info(f"stopbot_cmd triggered by user {update.effective_user.id}")
    await update.effective_message.reply_text("🛑 *Menghentikan Bridge-Telegram Service...*")
    os._exit(0)

async def sync_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    args = context.args
    if args:
        target_id = args[0].strip()
        target_path = BRAIN_DIR / target_id
        if not target_path.exists():
            await update.effective_message.reply_text(
                f"❌ Sesi `{target_id}` tidak ditemukan di server.\nKetik `/sessions` untuk melihat daftar riwayat sesi.",
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return
            
        info = get_session_details(target_id)
        session.conversation_id = target_id
        session.turns = info["turns"]
        session.last_sync_mtime = info["mtime"]
        session.save_session()
        prompt_preview = f"\n📌 *Dialog Terakhir*: _{info['last_user_prompt'][:120]}..._" if info['last_user_prompt'] else ""
        await update.effective_message.reply_text(
            f"🔄 *Berhasil Terhubung ke Sesi CLI Target!*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 *Conversation ID*: `{target_id}`\n"
            f"⏱️ *Waktu Aktif*: `{info['datetime_str']}`\n"
            f"💬 *Turns*: `{info['turns']}` turns{prompt_preview}\n\n"
            f"🟢 *Status*: Sesi ini sekarang aktif. Anda dapat langsung melanjutkan pekerjaan dari Telegram.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    # Auto-detect latest session from CLI
    recent = get_brain_sessions(limit=1)
    if not recent:
        await update.effective_message.reply_text("⚠️ Belum ada sesi CLI ditemukan di server.")
        return
        
    latest = recent[0]
    info = get_session_details(latest["id"])
    session.conversation_id = latest["id"]
    session.turns = info["turns"]
    session.last_sync_mtime = latest["mtime"]
    session.save_session()
    
    preview = f"\n📌 *Dialog Terakhir di Server*:\n_{info['last_user_prompt'][:120]}_" if info['last_user_prompt'] else ""
    await update.effective_message.reply_text(
        f"🔄 *Sinkronisasi Otomatis dengan CLI Selesai!*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 *Sesi Aktif*: `{latest['id']}`\n"
        f"⏱️ *Terakhir Aktif di CLI*: `{info['datetime_str']}`\n"
        f"💬 *Jumlah Turn*: `{info['turns']}` turns\n"
        f"🧠 *Model*: `{session.active_model}`{preview}\n\n"
        f"🟢 *Status*: Sesi terminal CLI dan Telegram terhubung 100%. Anda dapat menutup terminal CLI kapan saja tanpa kehilangan konteks.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def sessions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    sessions_list = get_brain_sessions(limit=5)
    if not sessions_list:
        await update.effective_message.reply_text("⚠️ Belum ada riwayat sesi tersimpan di server.")
        return
        
    lines = []
    for idx, s in enumerate(sessions_list, 1):
        details = get_session_details(s["id"])
        is_cur = " 👈 [AKTIF]" if s["id"] == session.conversation_id else ""
        prompt_prev = details["last_user_prompt"][:50].replace("\n", " ") if details["last_user_prompt"] else "(Awal percakapan)"
        lines.append(
            f"*{idx}.* `{s['id'][:18]}...`{is_cur}\n"
            f"   🆔 `{s['id']}`\n"
            f"   ⏱️ `{details['datetime_str']}` | 💬 `{details['turns']}` turns\n"
            f"   📌 _{prompt_prev}_"
        )
        
    text = (
        "📚 *Daftar Sesi Kerja CLI di Server*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        + "\n\n".join(lines) +
        "\n\n💡 *Ganti Sesi*: Ketik `/sync <id>` untuk menghubungkan sesi tertentu."
    )
    await send_chunked_message(update, text, parse_mode=constants.ParseMode.MARKDOWN)

async def autosync_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    args = context.args
    if args:
        val = args[0].lower().strip()
        if val in ["on", "enable", "true", "1", "ya", "aktif"]:
            session.auto_sync_cli = True
        elif val in ["off", "disable", "false", "0", "tidak", "mati"]:
            session.auto_sync_cli = False
        session.save_session()
        
    status_str = "🟢 *AKTIF*" if session.auto_sync_cli else "🔴 *NONAKTIF*"
    await update.effective_message.reply_text(
        f"⚙️ *Auto-Sync CLI Continuum*: {status_str}\n\n"
        "• Jika aktif, bot otomatis mendeteksi dan menyambung pekerjaan dari terminal AGY CLI saat terminal ditutup.\n"
        "• Atur status: `/autosync on` atau `/autosync off`",
        parse_mode=constants.ParseMode.MARKDOWN
    )

## --- FILE TRANSFER & DOWNLOAD HELPERS ---

def extract_destination_path(caption: Optional[str], default_name: str) -> Path:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if not caption:
        return DOWNLOADS_DIR / default_name
    
    m = re.search(r'(?:simpan\s+(?:di|ke)|save\s+to)\s+([a-zA-Z]:[^\r\n]+|[\w\-\.\/\\]+)', caption, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().strip('"\'')
        p = Path(raw)
        if not p.is_absolute():
            p = DOWNLOADS_DIR / raw
        if p.is_dir() or raw.endswith(("\\", "/")) or not p.suffix:
            p.mkdir(parents=True, exist_ok=True)
            return p / default_name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return DOWNLOADS_DIR / default_name

async def send_local_file_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_path: str):
    raw_path = raw_path.strip().strip('"\'')
    p = Path(raw_path)
    if not p.is_absolute():
        candidates = [
            BRIDGE_DIR / raw_path,
            WORKSPACE_DIR / raw_path,
            DOWNLOADS_DIR / raw_path,
            Path.home() / "Downloads" / raw_path,
        ]
        found = False
        for c in candidates:
            if c.exists():
                p = c
                found = True
                break
        if not found:
            p = BRIDGE_DIR / raw_path
            
    if not p.exists():
        await update.effective_message.reply_text(
            f"❌ *Berkas Tidak Ditemukan di PC*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nPath yang dicari:\n`{p}`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
        
    if p.is_dir():
        files = list(p.iterdir())[:15]
        flist = "\n".join([f"• `{f.name}`" + (" (folder)" if f.is_dir() else f" ({format_bytes(f.stat().st_size)})") for f in files])
        await update.effective_message.reply_text(
            f"📁 *`{p.name}` adalah Folder / Direktori*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Isi folder:\n{flist}\n\n💡 Ketik `/get {p}\\{p.name}\\<nama_file>` untuk mengambil berkas spesifik.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    size_bytes = p.stat().st_size
    size_str = format_bytes(size_bytes)
    
    if size_bytes > 50 * 1024 * 1024:
        await update.effective_message.reply_text(
            f"⚠️ *File Terlalu Besar untuk Telegram Bot API*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 *Nama*: `{p.name}`\n"
            f"📊 *Ukuran*: `{size_str}`\n"
            f"📂 *Lokasi*: `{p}`\n\n"
            f"ℹ️ Telegram membatasi upload bot maksimal *50 MB*.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    status_msg = await update.effective_message.reply_text(
        f"📤 *Mengirim berkas dari PC ke Telegram...*\n📁 `{p.name}` ({size_str})",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    
    try:
        with open(p, "rb") as f:
            caption = f"📄 *{p.name}*\n📊 Ukuran: `{size_str}`\n📂 Path PC: `{p}`"
            if p.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                try:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=f,
                        caption=caption,
                        parse_mode=constants.ParseMode.MARKDOWN
                    )
                    await status_msg.delete()
                    return
                except Exception:
                    f.seek(0)
                    try:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=f,
                            caption=f"📄 {p.name}\n📊 Ukuran: {size_str}\n📂 Path PC: {p}",
                            parse_mode=None
                        )
                        await status_msg.delete()
                        return
                    except Exception:
                        f.seek(0)
                    
            try:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=p.name,
                    caption=caption,
                    parse_mode=constants.ParseMode.MARKDOWN
                )
            except Exception:
                f.seek(0)
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=p.name,
                    caption=f"📄 {p.name}\n📊 Ukuran: {size_str}\n📂 Path PC: {p}",
                    parse_mode=None
                )
            await status_msg.delete()
    except Exception as e:
        logger.error(f"Error sending file {p}: {e}")
        await status_msg.edit_text(f"❌ Gagal mengirim berkas: `{e}`")

async def getfile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    if not context.args:
        await update.effective_message.reply_text(
            "📥 *Ambil Berkas dari PC*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Format: `/get <path_file>`\n\n"
            "💡 *Contoh Penggunaan*:\n"
            "• `/get bridge_telegram.py`\n"
            "• `/get config.json`\n"
            "• `/get active_session.json`\n"
            "• `/get bridge_telegram.log`\n\n"
            "Bisa juga langsung ketik: `kirim file <path>`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
        
    raw_path = " ".join(context.args).strip()
    await send_local_file_to_user(update, context, raw_path)

async def download_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    if not context.args:
        await update.effective_message.reply_text(
            "🌐 *Download dari URL ke PC*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Format: `/download <url> [target_path]`\n\n"
            "💡 *Contoh*:\n"
            "• `/download https://example.com/data.zip`\n"
            "• `/download https://example.com/logo.png E:\\Alfan\\logo.png`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
        
    url = context.args[0].strip()
    custom_target = " ".join(context.args[1:]).strip().strip('"\'') if len(context.args) > 1 else None
    
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if custom_target:
        target_path = Path(custom_target)
        if not target_path.is_absolute():
            target_path = DOWNLOADS_DIR / custom_target
    else:
        url_clean = url.split("?")[0].rstrip("/")
        fname = url_clean.split("/")[-1]
        if not fname or "." not in fname:
            fname = f"download_{int(time.time())}.bin"
        target_path = DOWNLOADS_DIR / fname

    target_path.parent.mkdir(parents=True, exist_ok=True)
    status_msg = await update.effective_message.reply_text(
        f"⏳ *Mengunduh dari Web ke PC...*\n🌐 `{url}`\n🎯 Target: `{target_path}`",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    
    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(target_path, "wb") as f:
                f.write(resp.content)
                
        size_str = format_bytes(target_path.stat().st_size)
        await status_msg.edit_text(
            f"✅ *Unduhan Berhasil Disimpan di PC!*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 *Berkas*: `{target_path.name}`\n"
            f"📊 *Ukuran*: `{size_str}`\n"
            f"📂 *Lokasi PC*: `{target_path}`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        await status_msg.edit_text(f"❌ Gagal mengunduh berkas: `{e}`")

# --- MULTI-MODAL HANDLERS (PHOTO & DOCUMENT) ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    photo = update.message.photo[-1]
    caption = update.message.caption or ""
    
    default_name = f"photo_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    target_path = extract_destination_path(caption, default_name)
    
    photo_file = await context.bot.get_file(photo.file_id)
    await photo_file.download_to_drive(str(target_path))
    
    size_str = format_bytes(target_path.stat().st_size)
    
    is_save_only = False
    if caption:
        lower_cap = caption.lower().strip()
        if re.match(r'^(?:simpan|save|download|unduh|upload)(?:\s+(?:di|ke|to|foto|gambar|ini).*)?$', lower_cap):
            is_save_only = True
            
    if is_save_only:
        msg_photo = (
            "> 🖼️ *Foto Disimpan di PC*\n"
            ">\n"
            f"> 📊 Ukuran: `{size_str}`\n"
            f"> 📂 Lokasi PC: `{target_path}`\n\n"
            "_Tersimpan di PC._"
        )
        await send_chunked_message(update, msg_photo)
        return
    
    analysis_caption = caption if caption else "Analisa dan jelaskan isi gambar ini secara detail."
    chat_id = update.effective_chat.id
    prompt = f"[ANALISA LAMPIRAN GAMBAR TERSIMPAN DI: {target_path}]\n{analysis_caption}"
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        logger.error(f"Error analyzing photo: {e}")
        await update.effective_message.reply_text(f"❌ Error saat analisa AI: `{e}`")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    doc = update.message.document
    if not doc:
        return
        
    caption = update.message.caption or ""
    clean_name = re.sub(r'[^\w\-_\.]', '_', doc.file_name or "document.txt")
    target_path = extract_destination_path(caption, f"{int(time.time())}_{clean_name}")
    
    doc_file = await context.bot.get_file(doc.file_id)
    await doc_file.download_to_drive(str(target_path))
    
    size_str = format_bytes(target_path.stat().st_size)
    
    is_save_only = False
    if caption:
        lower_cap = caption.lower().strip()
        if re.match(r'^(?:simpan|save|download|unduh|upload)(?:\s+(?:di|ke|to|file|ini).*)?$', lower_cap):
            is_save_only = True
        
    if is_save_only or not caption:
        if is_save_only:
            msg_doc = (
                "> 📥 *Berkas Disimpan di PC*\n"
                ">\n"
                f"> 📁 Nama: `{doc.file_name}`\n"
                f"> 📊 Ukuran: `{size_str}`\n"
                f"> 📂 Lokasi PC: `{target_path}`\n\n"
                "_Tersimpan di PC._"
            )
            await send_chunked_message(update, msg_doc)
        return
    
    chat_id = update.effective_chat.id
    prompt = f"[ANALISA LAMPIRAN BERKAS TERSIMPAN DI: {target_path}]\n{caption}"
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
    try:
        resp, data = await execute_agy_turn(prompt)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        logger.error(f"Error analyzing document: {e}")
        await update.effective_message.reply_text(f"❌ Error saat analisa AI: `{e}`")

# --- TASK QUEUE & ASYNC AGENT WORKER ---
task_queue = asyncio.Queue()

async def task_queue_worker(app: Application):
    """
    Background worker that continuously executes queued tasks sequentially.
    Ensures that when Tuan All gives additional commands while one task is in progress,
    they are safely queued, acknowledged instantly, and executed in order without dropping anything.
    """
    while True:
        try:
            item = await task_queue.get()
            update, context, text = item
            chat_id = update.effective_chat.id
            
            # Wait until previous active task is completely finished
            while is_turn_in_progress:
                await asyncio.sleep(0.5)

            stop_typing = asyncio.Event()
            typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
            
            try:
                resp, data = await execute_agy_turn(text)
                stop_typing.set()
                await typing_task
                await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
                await auto_dispatch_files_from_response(update, context, resp)
            except Exception as e:
                stop_typing.set()
                logger.error(f"Error executing queued task: {e}")
                await update.effective_message.reply_text(f"❌ *Engine Error (Antrean):* `{str(e)}`", parse_mode=constants.ParseMode.MARKDOWN)
            finally:
                task_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as q_ex:
            logger.error(f"Error in task_queue_worker: {q_ex}")
            await asyncio.sleep(1.0)

# --- NATURAL MESSAGE HANDLER (DIRECT AGENT BRAIN) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    text = update.effective_message.text
    if not text:
        return

    chat_id = update.effective_chat.id
    
    # 1. Shell shortcut
    if text.startswith("!") or text.lower().startswith("cmd:"):
        cmd_to_run = text[1:].strip() if text.startswith("!") else text.split(":", 1)[1].strip()
        await update.effective_message.reply_text(f"⚡ *Menjalankan shell:* `{cmd_to_run}`...", parse_mode=constants.ParseMode.MARKDOWN)
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd_to_run],
                cwd=str(session.working_dir if session.working_dir.exists() else WORKSPACE_DIR),
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=0x08000000 if platform.system() == "Windows" else 0,
            )
            output = res.stdout if res.stdout else res.stderr
            if not output.strip():
                output = "(Perintah sukses tanpa text output)"
            await send_chunked_message(update, f"📤 *Output Shell*:\n```\n{output[:3500]}\n```", parse_mode=constants.ParseMode.MARKDOWN)
            return
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error: `{e}`")
            return

    # 2. Natural File Transfer Request from PC to User
    file_send_match = re.search(
        r'^(?:kirim(?:kan)?|ambil|send|get)\s+file\s+["\']?([a-zA-Z]:[^\r\n"\'<>]+|[\w\-\.\/\\]+\.[a-zA-Z0-9]+)["\']?',
        text.strip(),
        re.IGNORECASE
    )
    if file_send_match:
        target_f = file_send_match.group(1).strip()
        await send_local_file_to_user(update, context, target_f)
        return

    # 3. Natural Web Download to PC Request
    download_match = re.search(
        r'^(?:download|unduh|wget)\s+(https?://\S+)(?:\s+(?:ke|di|to\s+)?["\']?([a-zA-Z]:[^\r\n"\'<>]+|[\w\-\.\/\\]+)["\']?)?',
        text.strip(),
        re.IGNORECASE
    )
    if download_match:
        url = download_match.group(1).strip()
        custom_t = download_match.group(2).strip() if download_match.group(2) else None
        context.args = [url]
        if custom_t:
            context.args.append(custom_t)
        await download_cmd(update, context)
        return

    # 4. If an AGY task is already actively executing, handle progress inquiries instantly or enqueue additional commands
    if is_turn_in_progress or not task_queue.empty():
        is_progress_inquiry = bool(re.search(
            r'\b(?:progres[s]?|status|sampai\s+mana|lagi\s+(?:apa|ngapain)|update|lagi\s+ngerjain\s+apa|sedang\s+(?:apa|mengerjakan\s+apa)|(?:sudah|udah)\s+(?:selesai|beres)|gimana\s+hasilnya)\b',
            text,
            re.IGNORECASE
        ))
        elapsed = int(time.time() - current_task_start_time) if current_task_start_time > 0 else 0
        mins, secs = divmod(elapsed, 60)
        time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs} detik"

        if is_progress_inquiry:
            clean_task = re.sub(r'\[DIRECTIVE:.*?\]', '', current_running_task_desc, flags=re.DOTALL).strip()
            task_preview = (clean_task[:150] + "...") if len(clean_task) > 150 else clean_task
            if not task_preview:
                task_preview = "Eksekusi otonom sedang berlangsung" if is_turn_in_progress else "Mempersiapkan pemrosesan antrean tugas"

            q_count = task_queue.qsize()
            q_info = f"\n> 📋 Antrean: `{q_count} tugas menunggu`" if q_count > 0 else ""

            msg = (
                "> ⚡ *Status Eksekusi Agent*\n"
                ">\n"
                f"> 📌 Tugas: `{task_preview}`\n"
                f"> ⏱️ Waktu: `{time_str}`\n"
                f"> 🧠 Model: `{session.active_model}`\n"
                f"> 🟢 Engine `{BACKEND_PROVIDER}` aktif memproses instruksi.{q_info}\n\n"
                "_Hasil lengkap akan langsung dikirimkan ke chat setelah selesai._"
            )
            await send_chunked_message(update, msg)
            return
        else:
            await task_queue.put((update, context, text))
            q_size = task_queue.qsize()
            clean_new_task = (text[:120] + "...") if len(text) > 120 else text
            msg = (
                f"> 📥 *Perintah Masuk Antrean* `#{q_size}`\n"
                ">\n"
                f"> 📌 Tugas Baru: `{clean_new_task}`\n"
                f"> ⏳ Status: Menunggu tugas aktif selesai (`{time_str}`)\n\n"
                "_Otomatis diproses segera setelah tugas aktif selesai._"
            )
            await send_chunked_message(update, msg)
            return

    # 5. Native AI Agent Execution
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))

    try:
        resp, data = await execute_agy_turn(text)
        stop_typing.set()
        await typing_task
        await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
        await auto_dispatch_files_from_response(update, context, resp)
    except Exception as e:
        stop_typing.set()
        logger.error(f"Error during AGY execution: {e}")
        await update.effective_message.reply_text(f"❌ *Engine Error:* `{str(e)}`", parse_mode=constants.ParseMode.MARKDOWN)

# --- TELEGRAM APPROVAL & INTERACTIVE CALLBACK HANDLER ---

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles interactive button approvals/rejections from Tuan All directly in Telegram chat.
    Ensures that when an agent requests approval for a task, Tuan All can click [Setujui & Lanjutkan]
    or [Batalkan Tindakan], and the execution continues immediately and autonomously.
    """
    query = update.callback_query
    if not is_authorized(update):
        await query.answer("Akses tidak diizinkan.", show_alert=True)
        return
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id

    if data == "approval_confirm":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text("✅ *Persetujuan Diterima:* Melanjutkan eksekusi...", parse_mode=constants.ParseMode.MARKDOWN)
        prompt = "Persetujuan diberikan oleh Tuan All. Silakan lanjutkan eksekusi tindakan secara otonom hingga tuntas."
        
        if is_turn_in_progress or not task_queue.empty():
            await task_queue.put((update, context, prompt))
        else:
            stop_typing = asyncio.Event()
            typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
            try:
                resp, _ = await execute_agy_turn(prompt)
                stop_typing.set()
                await typing_task
                await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
                await auto_dispatch_files_from_response(update, context, resp)
            except Exception as e:
                stop_typing.set()
                logger.error(f"Error executing approved action: {e}")
                await query.message.reply_text(f"❌ *Engine Error:* `{str(e)}`")

    elif data == "approval_cancel":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text("❌ *Tindakan Dibatalkan* oleh Tuan All.", parse_mode=constants.ParseMode.MARKDOWN)
        prompt = "Tindakan dibatalkan oleh Tuan All. Jangan lakukan perubahan tersebut dan hentikan alur tersebut."
        
        if is_turn_in_progress or not task_queue.empty():
            await task_queue.put((update, context, prompt))
        else:
            stop_typing = asyncio.Event()
            typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
            try:
                resp, _ = await execute_agy_turn(prompt)
                stop_typing.set()
                await typing_task
                await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception as e:
                stop_typing.set()
                logger.error(f"Error executing cancelled action: {e}")
                await query.message.reply_text(f"❌ *Engine Error:* `{str(e)}`")

    elif data == "failover_resume":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        state = load_task_state()
        prompt_to_resume = state.get("prompt", "")
        conv_id = state.get("conversation_id")
        saved_model = state.get("model")

        if not prompt_to_resume:
            await query.message.reply_text("ℹ️ *Informasi:* Tidak ada tugas tertunda yang tersimpan di sistem.", parse_mode=constants.ParseMode.MARKDOWN)
            return

        clean_prompt = re.sub(r'\[DIRECTIVE:.*?\]', '', prompt_to_resume, flags=re.DOTALL).strip()
        preview = (clean_prompt[:120] + "...") if len(clean_prompt) > 120 else clean_prompt

        resume_notice = (
            "> ▶️ <b>Melanjutkan Tugas Tertunda</b>\n"
            ">\n"
            f"> 📌 <b>Tugas</b>: <code>{html.escape(preview)}</code>\n"
            f"> 🆔 <b>Sesi</b>: <code>{conv_id or 'Sesi Baru'}</code>\n"
            f"> 🧠 <b>Model</b>: <code>{saved_model or session.active_model}</code>\n\n"
            "<i>Sistem backup melanjutkan eksekusi tugas secara otonom...</i>"
        )
        await query.message.reply_text(resume_notice, parse_mode=constants.ParseMode.HTML)

        # Restore session conversation ID so context continuity is preserved
        if conv_id:
            session.telegram_conv_id = conv_id
            session.conversation_id = conv_id
            session.save_session()

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(send_continuous_typing(context, chat_id, stop_typing))
        try:
            resp, _ = await execute_agy_turn(prompt_to_resume, model=saved_model)
            stop_typing.set()
            await typing_task
            await send_chunked_message(update, resp, parse_mode=constants.ParseMode.MARKDOWN)
            await auto_dispatch_files_from_response(update, context, resp)
        except Exception as e:
            stop_typing.set()
            logger.error(f"Error resuming failover task: {e}")
            await query.message.reply_text(f"❌ *Engine Error saat melanjutkan tugas:* `{str(e)}`")

    elif data == "failover_restart":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        # Mark task state as cancelled / reset
        state = load_task_state()
        state["status"] = "cancelled"
        state["updated_at"] = time.time()
        save_task_state(state)

        # Reset session
        session.reset_session()

        restart_notice = (
            "> 🔄 <b>Sesi Direset ke Awal</b>\n"
            ">\n"
            "> ✅ Tugas tertunda dibatalkan dan memori sesi dibersihkan.\n"
            "> 🤖 Server backup siap menerima instruksi baru dari awal."
        )
        await query.message.reply_text(restart_notice, parse_mode=constants.ParseMode.HTML)

# --- REALTIME SYNC DAEMON ---

async def realtime_sync_loop(app: Application):
    """
    Continuous realtime background daemon.
    Monitors CLI terminal process and brain transcripts every 3 seconds.
    When the CLI terminal is closed or updated, it immediately syncs state to active_session.json
    and notifies Tuan All on Telegram so that conversation continuum is 100% realtime.
    """
    was_cli_running = is_cli_interactive_running()
    last_notified_conv = None
    last_notified_turns = -1

    while True:
        try:
            await asyncio.sleep(3.0)
            if is_turn_in_progress:
                continue

            # 1. Real-time Model Synchronization Check (CLI -> Telegram Chat)
            changed_model = session.sync_model_from_settings()
            if changed_model:
                msg = (
                    "> 🔄 *Sinkronisasi Model Real-Time*\n"
                    ">\n"
                    "> 🖥️ Model CLI PC dialihkan ke:\n"
                    f"> 🧠 `{changed_model}`\n\n"
                    "_Prompt berikutnya di chat otomatis menggunakan model ini._"
                )
                try:
                    html_msg = markdown_to_telegram_html(msg)
                    await app.bot.send_message(
                        chat_id=AUTHORIZED_USER_ID,
                        text=html_msg,
                        parse_mode=constants.ParseMode.HTML
                    )
                except Exception as e:
                    logger.warning(f"Failed to send model sync notification: {e}")
                    try:
                        await app.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=msg)
                    except Exception:
                        pass

            cli_now_running = is_cli_interactive_running()

            # Event: CLI terminal was running and just CLOSED
            if was_cli_running and not cli_now_running:
                logger.info("Interactive CLI terminal closed. Running immediate realtime sync...")
                synced = session.check_and_sync_with_latest_cli(force=True)
                if synced:
                    c_id = synced["id"]
                    t_count = synced["turns"]
                    if c_id != last_notified_conv or t_count != last_notified_turns:
                        last_notified_conv = c_id
                        last_notified_turns = t_count
                        preview = f"\n> 📌 Aktivitas: _{synced['last_user_prompt'][:100]}..._" if synced.get('last_user_prompt') else ""
                        msg = (
                            "> 🔄 *CLI Continuum Terhubung*\n"
                            ">\n"
                            "> 🖥️ Terminal PC ditutup. Sesi kerja tersambung ke Telegram.\n"
                            f"> 🆔 Sesi: `{c_id}`\n"
                            f"> 💬 Turn: `{t_count}`\n"
                            f"> 🧠 Model: `{session.active_model}`{preview}\n\n"
                            "_Siap menerima instruksi lanjutan di Telegram._"
                        )
                        try:
                            html_msg = markdown_to_telegram_html(msg)
                            await app.bot.send_message(
                                chat_id=AUTHORIZED_USER_ID,
                                text=html_msg,
                                parse_mode=constants.ParseMode.HTML
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send realtime notification: {e}")
                            try:
                                await app.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=msg)
                            except Exception:
                                pass

            # Event: CLI is closed, keep syncing any updates
            elif not cli_now_running:
                session.check_and_sync_with_latest_cli()

            # Continuous vault persistence guard
            protect_and_restore_auth_vault()

            was_cli_running = cli_now_running

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in realtime_sync_loop: {e}")
            await asyncio.sleep(5.0)

def check_internet_reachability() -> bool:
    """
    Checks if active internet connection is available by pinging reliable global DNS/Telegram endpoints.
    """
    targets = [
        ("1.1.1.1", 53),
        ("8.8.8.8", 53),
        ("149.154.166.110", 443),
    ]
    for host, port in targets:
        try:
            s = socket.create_connection((host, port), timeout=3.0)
            s.close()
            return True
        except OSError:
            continue
    return False

FAILOVER_STATE_FILE = BRIDGE_DIR / "failover_state.json"

def load_failover_state() -> dict:
    if FAILOVER_STATE_FILE.exists():
        try:
            with open(FAILOVER_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "node_id": platform.node() or "default-node",
        "current_role": "active",
        "last_active_heartbeat": time.time(),
        "primary_misses": 0
    }

def save_failover_state(data: dict):
    try:
        with open(FAILOVER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save failover state: {e}")

async def sync_remote_session_context(bot, conv_id: Optional[str] = None):
    """
    Synchronizes conversation context across nodes via Telegram pinned message or draft state.
    Allows backup node to pick up the conversation seamlessly without losing context.
    """
    if not conv_id:
        return
    try:
        ctx_payload = json.dumps({
            "type": "BRIDGE_CONTEXT_SYNC",
            "conversation_id": conv_id,
            "turns": session.turns,
            "model": session.active_model,
            "working_dir": str(session.working_dir),
            "updated_at": time.time(),
            "node": platform.node()
        })
        # Save locally as primary checkpoint
        session.save_session()
    except Exception as e:
        logger.debug(f"Session context sync: {e}")

# --- TASK STATE PERSISTENCE & FAILOVER CONTINUITY ---

def load_task_state() -> dict:
    if TASK_STATE_FILE.exists():
        try:
            with open(TASK_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_task_state(data: dict):
    try:
        with open(TASK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save task state: {e}")

def record_task_start(prompt: str, conv_id: Optional[str] = None, model: Optional[str] = None):
    """
    Persistently records active task details when execution begins.
    If the primary server dies mid-task, the standby node reads this to resume seamlessly.
    """
    state = {
        "status": "in_progress",
        "prompt": prompt,
        "conversation_id": conv_id,
        "model": model or session.active_model,
        "working_dir": str(session.working_dir),
        "node": platform.node(),
        "start_time": time.time(),
        "updated_at": time.time(),
    }
    save_task_state(state)

def record_task_end(response_summary: str = "", success: bool = True):
    """
    Updates task state to completed or failed upon turn termination.
    """
    state = load_task_state()
    state.update({
        "status": "completed" if success else "failed",
        "response_summary": (response_summary[:200] + "...") if len(response_summary) > 200 else response_summary,
        "end_time": time.time(),
        "updated_at": time.time(),
    })
    save_task_state(state)

async def check_and_prompt_failover_task(bot):
    """
    Checks if there is an interrupted task from a previous crash or failover.
    If yes, prompts Tuan All via Telegram with interactive buttons:
    [▶️ Lanjutkan Tugas] or [🔄 Mulai dari Awal].
    """
    state = load_task_state()
    if not state or state.get("status") != "in_progress":
        return

    prompt = state.get("prompt", "")
    conv_id = state.get("conversation_id") or session.conversation_id or "default"
    origin_node = state.get("node", "Server Utama")
    start_ts = state.get("start_time", 0.0)
    elapsed = int(time.time() - start_ts) if start_ts > 0 else 0
    mins, secs = divmod(elapsed, 60)
    time_str = f"{mins}m {secs}s lalu" if mins > 0 else f"{secs} detik lalu"

    clean_prompt = re.sub(r'\[DIRECTIVE:.*?\]', '', prompt, flags=re.DOTALL).strip()
    preview = (clean_prompt[:250] + "...") if len(clean_prompt) > 250 else clean_prompt

    msg = (
        "> ⚠️ <b>Peralihan Server Terdeteksi (Failover Recovery)</b>\n"
        ">\n"
        f"> 🔴 Server sebelumnya (<code>{origin_node}</code>) terhenti saat menjalankan tugas.\n"
        f"> 📌 <b>Tugas Tertunda</b>: <code>{html.escape(preview)}</code>\n"
        f"> 🆔 <b>ID Sesi</b>: <code>{conv_id}</code>\n"
        f"> ⏱️ <b>Dimulai</b>: <code>{time_str}</code>\n\n"
        "<i>Apakah Tuan All ingin melanjutkan tugas yang belum selesai ini atau memulai dari awal?</i>"
    )

    keyboard = [
        [
            InlineKeyboardButton("▶️ Lanjutkan Tugas", callback_data="failover_resume"),
            InlineKeyboardButton("🔄 Mulai dari Awal", callback_data="failover_restart"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=msg,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=reply_markup,
        )
        logger.info(f"Failover recovery notification sent to Telegram for task: {preview[:60]}")
    except Exception as e:
        logger.error(f"Failed to send failover recovery message: {e}")

async def check_peer_node_polling(bot_token: str) -> bool:
    """
    Checks if another instance is actively polling Telegram by testing a non-destructive getUpdates call.
    If another node is already polling with the same token, Telegram returns 409 Conflict.
    Returns: True if another node is active (Conflict 409), False if polling is free.
    """
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset=-1&limit=1&timeout=1"
            res = await client.get(url)
            if res.status_code == 409:
                return True
            return False
    except Exception:
        return False

def load_server_state() -> dict:
    if SERVER_STATE_FILE.exists():
        try:
            with open(SERVER_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_server_state(data: dict):
    try:
        with open(SERVER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save server state: {e}")

async def internet_monitor_loop(app: Application):
    """
    Continuously monitors server reboot/restart events and internet connection status.
    When the server restarts or recovers from an offline/shutdown state,
    automatically sends an instant Telegram notification to Tuan All.
    """
    was_online = True
    offline_start_time = 0.0
    initial_check_done = False

    # Server boot & restart detection
    server_state = load_server_state()
    current_boot_time = int(psutil.boot_time())
    last_boot_time = server_state.get("last_boot_time", 0)
    last_heartbeat = server_state.get("last_heartbeat", 0)
    last_notified_boot = server_state.get("last_notified_boot", 0)
    restart_notified = (current_boot_time == last_notified_boot)

    logger.info(f"Server Monitor: Current Boot Time={current_boot_time}, Last Boot={last_boot_time}, Restart Notified={restart_notified}")

    while True:
        try:
            await asyncio.sleep(8.0)
            is_online = await asyncio.to_thread(check_internet_reachability)

            # Update continuous heartbeat in background
            now_ts = int(time.time())
            server_state["last_boot_time"] = current_boot_time
            server_state["last_heartbeat"] = now_ts
            save_server_state(server_state)

            # Case 1: Server RESTART / REBOOT DETECTED
            if is_online and not restart_notified and (current_boot_time != last_boot_time or last_boot_time == 0):
                boot_dt = datetime.datetime.fromtimestamp(current_boot_time).strftime("%Y-%m-%d %H:%M:%S")
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                down_str = ""
                if last_heartbeat > 0 and (current_boot_time > last_heartbeat or (now_ts - last_heartbeat) > 30):
                    downtime = max(0, current_boot_time - last_heartbeat)
                    mins, secs = divmod(downtime, 60)
                    hrs, mins = divmod(mins, 60)
                    if hrs > 0:
                        down_str = f"\n> ⏳ Estimasi Downtime: `{hrs}j {mins}m {secs}s`"
                    elif mins > 0:
                        down_str = f"\n> ⏳ Estimasi Downtime: `{mins}m {secs}s`"
                    else:
                        down_str = f"\n> ⏳ Estimasi Downtime: `{secs} detik`"

                msg = (
                    "> 🖥️ *Host System Menyala Kembali*\n"
                    ">\n"
                    "> 🟢 Status: PC / Host Server telah restart dan kembali aktif.\n"
                    f"> ⏰ Waktu Boot: `{boot_dt}`{down_str}\n"
                    f"> ⏱️ Waktu Online: `{now_str}`\n"
                    f"> 🧠 Model Aktif: `{session.active_model}`\n"
                    "> 🤖 Service: `Bridge-Telegram Siap`\n\n"
                    "_Chatbot otomatis terhubung dan siap menerima instruksi._"
                )
                try:
                    html_msg = markdown_to_telegram_html(msg)
                    await app.bot.send_message(
                        chat_id=AUTHORIZED_USER_ID,
                        text=html_msg,
                        parse_mode=constants.ParseMode.HTML
                    )
                    logger.info("Server restart notification sent to Telegram.")
                    restart_notified = True
                    server_state["last_notified_boot"] = current_boot_time
                    save_server_state(server_state)
                except Exception as ne:
                    logger.warning(f"Failed to send server restart notification: {ne}")

            # Case 2: Internet was OFFLINE, and now RECOVERED back to ONLINE
            elif not was_online and is_online:
                offline_dur_str = ""
                if offline_start_time > 0:
                    dur = int(time.time() - offline_start_time)
                    mins, secs = divmod(dur, 60)
                    offline_dur_str = f" setelah offline selama `{mins}m {secs}s`" if mins > 0 else f" setelah offline selama `{secs} detik`"

                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msg = (
                    "> 🌐 *Internet Terhubung Kembali*\n"
                    ">\n"
                    f"> 🟢 Status: Koneksi internet PC/Server telah pulih{offline_dur_str}.\n"
                    f"> ⏱️ Waktu: `{now_str}`\n"
                    f"> 🤖 Bot: `Bridge-Telegram Online`\n\n"
                    "_Chatbot siap menerima perintah kembali._"
                )
                try:
                    html_msg = markdown_to_telegram_html(msg)
                    await app.bot.send_message(
                        chat_id=AUTHORIZED_USER_ID,
                        text=html_msg,
                        parse_mode=constants.ParseMode.HTML
                    )
                    logger.info("Internet recovery notification sent to Telegram.")
                except Exception as ne:
                    logger.warning(f"Failed to send internet recovery notification: {ne}")

                offline_start_time = 0.0

            # Case 3: Internet just went OFFLINE
            elif was_online and not is_online:
                offline_start_time = time.time()
                logger.warning("Internet connection lost. Waiting for network recovery...")

            if not initial_check_done:
                initial_check_done = True
                if not is_online:
                    offline_start_time = time.time()

            was_online = is_online

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in internet_monitor_loop: {e}")
            await asyncio.sleep(5.0)

async def post_init(application: Application):
    logger.info("Starting background Realtime CLI Sync Watcher daemon...")
    asyncio.create_task(realtime_sync_loop(application))
    logger.info("Starting background Task Queue Worker...")
    asyncio.create_task(task_queue_worker(application))
    logger.info("Starting background Internet Connection Monitor daemon...")
    asyncio.create_task(internet_monitor_loop(application))
    logger.info("Checking for interrupted tasks from previous failover / crash...")
    asyncio.create_task(check_and_prompt_failover_task(application.bot))

# --- MAIN RUNNER ---

def main():
    logger.info("Initializing Bridge-Telegram Gateway...")
    
    req = HTTPXRequest(
        connect_timeout=25.0,
        read_timeout=60.0,
        write_timeout=30.0,
        pool_timeout=25.0,
    )
    app = ApplicationBuilder().token(BOT_TOKEN).request(req).post_init(post_init).build()

    # Register Command Handlers
    app.add_handler(CommandHandler(["start"], start_cmd))
    app.add_handler(CommandHandler(["help"], help_cmd))
    app.add_handler(CommandHandler(["usage"], usage_cmd))
    app.add_handler(CommandHandler(["quota"], quota_cmd))
    app.add_handler(CommandHandler(["model", "models"], model_cmd))
    app.add_handler(CommandHandler(["backend", "provider"], backend_cmd))
    app.add_handler(CommandHandler(["status"], status_cmd))
    app.add_handler(CommandHandler(["cd", "workspace", "pwd"], cd_cmd))
    app.add_handler(CommandHandler(["ls", "dir"], ls_cmd))
    app.add_handler(CommandHandler(["clear", "reset"], clear_cmd))
    app.add_handler(CommandHandler(["sync"], sync_cmd))
    app.add_handler(CommandHandler(["sessions", "history"], sessions_cmd))
    app.add_handler(CommandHandler(["autosync"], autosync_cmd))
    app.add_handler(CommandHandler(["plan"], plan_cmd))
    app.add_handler(CommandHandler(["goal"], goal_cmd))
    app.add_handler(CommandHandler(["boost"], boost_cmd))
    app.add_handler(CommandHandler(["browser"], browser_cmd))
    app.add_handler(CommandHandler(["grillme"], grillme_cmd))
    app.add_handler(CommandHandler(["teamwork"], teamwork_cmd))
    app.add_handler(CommandHandler(["humanize", "humanizer"], humanize_cmd))
    app.add_handler(CommandHandler(["learn"], learn_cmd))
    app.add_handler(CommandHandler(["schedule"], schedule_cmd))
    app.add_handler(CommandHandler(["get", "sendfile", "fetch"], getfile_cmd))
    app.add_handler(CommandHandler(["download", "wget"], download_cmd))
    app.add_handler(CommandHandler(["restart", "reload"], restart_cmd))
    app.add_handler(CommandHandler(["exit", "quit"], exit_cmd))
    app.add_handler(CommandHandler(["stopbot", "killbot"], stopbot_cmd))

    # Media & Document Handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Natural Message Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Interactive Button Callback Handler (Approvals)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    failover_cfg = _cfg.get("failover", {})
    failover_enabled = failover_cfg.get("enabled", True)
    configured_role = failover_cfg.get("role", "auto").lower()

    logger.info("Bridge-Telegram is initializing high-availability gateway...")
    logger.info(f"Authorized ID: {AUTHORIZED_USER_ID} | Provider: {BACKEND_PROVIDER} | Failover: {failover_enabled} (Role: {configured_role})")

    # If configured as standby or in auto mode, check if a peer primary node is already active
    is_standby = False
    if failover_enabled and configured_role in ["standby", "backup"]:
        is_standby = True
    elif failover_enabled and configured_role == "auto":
        peer_active = asyncio.run(check_peer_node_polling(BOT_TOKEN))
        if peer_active:
            is_standby = True
            logger.warning("Primary node detected actively polling Telegram! This node is now STANDBY (Auto-Failover Mode).")

    if is_standby:
        logger.info("Entering Standby Monitor Loop... Waiting for primary node to go offline before taking over.")
        check_interval = float(failover_cfg.get("standby_check_interval", 6.0))
        miss_threshold = int(failover_cfg.get("takeover_threshold_misses", 3))
        consecutive_offline_checks = 0

        while True:
            time.sleep(check_interval)
            peer_still_active = asyncio.run(check_peer_node_polling(BOT_TOKEN))
            if not peer_still_active:
                consecutive_offline_checks += 1
                logger.info(f"Primary node appear offline ({consecutive_offline_checks}/{miss_threshold})...")
                if consecutive_offline_checks >= miss_threshold:
                    logger.warning("Primary node is DOWN! Triggering automatic takeover to ACTIVE PRIMARY!")
                    break
            else:
                consecutive_offline_checks = 0

    while True:
        try:
            app.run_polling(drop_pending_updates=True, bootstrap_retries=-1)
            break
        except Exception as e:
            err_str = str(e).lower()
            if "conflict" in err_str or "terminated by other getupdates" in err_str:
                logger.warning("Telegram polling conflict detected (another primary server is active). Entering Standby Sleep...")
                time.sleep(10)
                continue
            logger.error(f"Error in run_polling: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    
    logger.info("Bridge-Telegram run_polling has terminated.")

if __name__ == "__main__":
    while True:
        try:
            main()
            break
        except SystemExit:
            break
        except Exception as e:
            logger.exception(f"Fatal error in main: {e}. Restarting bridge in 5 seconds...")
            time.sleep(5)
