import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

BRIDGE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BRIDGE_DIR / "config.json"
CONFIG_EXAMPLE_FILE = BRIDGE_DIR / "config.example.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "bot_token": "",
    "authorized_user_id": 0,
    "backend_provider": "auto",
    "working_directory": "",
    "downloads_directory": "",
    "antigravity": {
        "binary_path": "",
        "hub_path": "",
        "dangerously_skip_permissions": True,
        "timeout_seconds": 180.0
    },
    "openai_compatible": {
        "api_base": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o",
        "system_prompt": "You are a helpful, production-grade autonomous AI software engineer."
    },
    "nine_router": {
        "api_base": "https://api.9router.com/v1",
        "api_key": "",
        "model": "deepseek-chat"
    },
    "hermes": {
        "api_base": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "hermes-3-llama-3.1-8b"
    },
    "cli_agent": {
        "binary_path": "",
        "args_template": ["-p", "{prompt}"]
    },
    "failover": {
        "enabled": True,
        "role": "auto",
        "standby_check_interval": 6.0,
        "takeover_threshold_misses": 3
    }
}

class ConfigManager:
    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    self._deep_update(cfg, user_cfg)
            except Exception as e:
                print(f"[ConfigManager] Error reading config.json: {e}")
        else:
            token_env = os.getenv("TELEGRAM_BOT_TOKEN", "")
            owner_env = int(os.getenv("TELEGRAM_AUTHORIZED_ID", "0")) if os.getenv("TELEGRAM_AUTHORIZED_ID") else 0
            cfg["bot_token"] = token_env
            cfg["authorized_user_id"] = owner_env
            cfg["working_directory"] = str(Path.cwd())
            cfg["downloads_directory"] = str(BRIDGE_DIR / "downloads")
            self.save(cfg)

        # Environment variable overrides
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            cfg["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
        if os.getenv("TELEGRAM_AUTHORIZED_ID"):
            try:
                cfg["authorized_user_id"] = int(os.environ["TELEGRAM_AUTHORIZED_ID"])
            except ValueError:
                pass
        if os.getenv("BACKEND_PROVIDER"):
            cfg["backend_provider"] = os.environ["BACKEND_PROVIDER"]
        if os.getenv("OPENAI_API_BASE"):
            cfg["openai_compatible"]["api_base"] = os.environ["OPENAI_API_BASE"]
        if os.getenv("OPENAI_API_KEY"):
            cfg["openai_compatible"]["api_key"] = os.environ["OPENAI_API_KEY"]

        self.config = cfg
        return self.config

    def save(self, cfg: Optional[Dict[str, Any]] = None):
        if cfg is not None:
            self.config = cfg
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"[ConfigManager] Error saving config.json: {e}")

    def _deep_update(self, base: dict, update: dict):
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_update(base[k], v)
            else:
                base[k] = v

config_mgr = ConfigManager()
