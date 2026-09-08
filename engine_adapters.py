"""
Universal Engine Adapters for Bridge-Telegram.
Supports:
- Google Antigravity (agy.exe)
- OpenAI-compatible APIs (OpenAI, vLLM, Ollama, OpenRouter)
- 9Router (multi-LLM proxy)
- Hermes Agent (Nous Research / Ollama / Local API)
- CLI Agents (OpenCode, Claude Code, Cline, etc.)
"""

import abc
import asyncio
import json
import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("BridgeTelegramAdapters")

class BaseAgentAdapter(abc.ABC):
    @abc.abstractmethod
    async def execute_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        working_dir: Optional[Path] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Executes a turn with the underlying AI agent engine.
        Returns (response_text, raw_metadata_dict).
        """
        pass

    @abc.abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """Returns engine health and details."""
        pass


class AntigravityAdapter(BaseAgentAdapter):
    def __init__(self, binary_path: Path, timeout: float = 180.0):
        self.binary_path = Path(binary_path)
        self.timeout = timeout

    async def execute_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        working_dir: Optional[Path] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        cwd = working_dir if working_dir and working_dir.exists() else Path.cwd()
        cmd = [
            str(self.binary_path),
            "--dangerously-skip-permissions",
            "--output-format", "json",
            "-p", prompt,
        ]
        if session_id:
            cmd.extend(["--conversation", session_id])
        if model:
            cmd.extend(["--model", model])

        kwargs: dict = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ("⚠️ Execution timed out after 3 minutes.", None)

        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()

        if not out_text:
            return (err_text if err_text else "⚠️ Empty response from Antigravity engine.", None)

        try:
            data = json.loads(out_text)
        except json.JSONDecodeError:
            start = out_text.find("{")
            end = out_text.rfind("}")
            if start != -1 and end > start:
                data = json.loads(out_text[start:end+1])
            else:
                return (out_text, None)

        resp_text = data.get("response", "").strip()
        return (resp_text if resp_text else "✅ Execution completed without text output.", data)

    async def get_status(self) -> Dict[str, Any]:
        exists = self.binary_path.exists()
        return {
            "name": "Google Antigravity Engine",
            "type": "native_cli",
            "binary": str(self.binary_path),
            "available": exists
        }


class OpenAICompatibleAdapter(BaseAgentAdapter):
    def __init__(self, api_base: str, api_key: str, default_model: str, system_prompt: str = ""):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key or "sk-dummy"
        self.default_model = default_model
        self.system_prompt = system_prompt or "You are an expert autonomous AI software engineer."
        self.conversations: Dict[str, list] = {}

    async def execute_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        working_dir: Optional[Path] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        cid = session_id or "default"
        if cid not in self.conversations:
            self.conversations[cid] = [
                {"role": "system", "content": self.system_prompt}
            ]

        self.conversations[cid].append({"role": "user", "content": prompt})

        # Keep context reasonable
        if len(self.conversations[cid]) > 40:
            self.conversations[cid] = [self.conversations[cid][0]] + self.conversations[cid][-30:]

        target_model = model or self.default_model
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": target_model,
            "messages": self.conversations[cid],
            "temperature": 0.3
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code != 200:
                    err_msg = f"API Error {res.status_code}: {res.text}"
                    logger.error(err_msg)
                    return (f"⚠️ *OpenAI API Error:*\n`{res.status_code}`: {res.text[:300]}", None)
                data = res.json()
                choice = data.get("choices", [{}])[0]
                reply = choice.get("message", {}).get("content", "").strip()
                self.conversations[cid].append({"role": "assistant", "content": reply})
                return (reply, data)
        except Exception as e:
            logger.error(f"OpenAICompatibleAdapter error: {e}")
            return (f"⚠️ *Connection Exception:*\n`{str(e)}`", None)

    async def get_status(self) -> Dict[str, Any]:
        return {
            "name": "OpenAI Compatible / 9Router / Hermes",
            "type": "api_rest",
            "base_url": self.api_base,
            "model": self.default_model,
            "available": True
        }


class SubprocessCLIAdapter(BaseAgentAdapter):
    """
    Adapter for external CLI AI agents like OpenCode, Claude Code, Hermes CLI.
    """
    def __init__(self, binary_path: str, args_template: list):
        self.binary_path = binary_path
        self.args_template = args_template

    async def execute_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        working_dir: Optional[Path] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        cwd = working_dir if working_dir and working_dir.exists() else Path.cwd()
        cmd = [self.binary_path]
        for arg in self.args_template:
            cmd.append(arg.replace("{prompt}", prompt).replace("{model}", model or ""))

        kwargs: dict = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
            out_text = stdout.decode("utf-8", errors="replace").strip()
            err_text = stderr.decode("utf-8", errors="replace").strip()
            return (out_text if out_text else err_text, {"raw_stdout": out_text})
        except Exception as e:
            return (f"⚠️ *CLI Execution Error:* `{e}`", None)

    async def get_status(self) -> Dict[str, Any]:
        return {
            "name": "External CLI Agent",
            "type": "cli_subcommand",
            "binary": self.binary_path,
            "available": True
        }


def auto_detect_engine(config: Dict[str, Any]) -> Tuple[str, str]:
    """
    Intelligently auto-detects what AI agent engine or LLM provider is available
    in the host environment without requiring manual configuration.
    
    Priority Order:
    1. Google Antigravity (agy.exe) — Checks configured path, standard local appdata, and PATH.
    2. Local Ollama / Hermes endpoint (checks if port 11434 is listening).
    3. 9Router endpoint (if 9router api_key or env exists).
    4. OpenAI-compatible / OpenRouter (if OPENAI_API_KEY or config key exists).
    5. External CLI agents (opencode, claude, cline, hermes in PATH).
    
    Returns: (provider_name, detection_reason_string)
    """
    import shutil
    import socket

    # 1. Check Google Antigravity
    agy_custom = config.get("antigravity", {}).get("binary_path")
    if agy_custom and Path(agy_custom).exists():
        return ("antigravity", f"Google Antigravity terdeteksi via custom path: {agy_custom}")

    agy_in_path = shutil.which("agy") or shutil.which("agy.exe")
    if agy_in_path:
        return ("antigravity", f"Google Antigravity terdeteksi di PATH sistem: {agy_in_path}")

    # Standard Windows AGY AppData location
    local_appdata = os.getenv("LOCALAPPDATA", "")
    if local_appdata:
        std_agy = Path(local_appdata) / "agy" / "bin" / "agy.exe"
        if std_agy.exists():
            return ("antigravity", f"Google Antigravity terdeteksi di AppData: {std_agy}")

    # 2. Check 9Router
    nr_key = config.get("nine_router", {}).get("api_key") or os.getenv("NINEROUTER_API_KEY")
    if nr_key and not nr_key.startswith("nr-..."):
        return ("nine_router", "9Router terdeteksi melalui API Key aktif.")

    # 3. Check Local Ollama / Hermes port (11434)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        res = s.connect_ex(("127.0.0.1", 11434))
        s.close()
        if res == 0:
            return ("hermes", "Local Hermes / Ollama service terdeteksi aktif di port 11434.")
    except Exception:
        pass

    # 4. Check OpenAI / OpenRouter Key
    oai_key = config.get("openai_compatible", {}).get("api_key") or os.getenv("OPENAI_API_KEY")
    if oai_key and not oai_key.startswith("sk-..."):
        return ("openai_compatible", "OpenAI / Compatible API terdeteksi melalui API Key aktif.")

    # 5. Check External CLI Agents in PATH
    for cli_name in ["opencode", "claude", "cline", "hermes"]:
        loc = shutil.which(cli_name)
        if loc:
            return ("cli_agent", f"CLI Agent '{cli_name}' terdeteksi di PATH: {loc}")

    # Fallback to config preference or antigravity default
    configured = config.get("backend_provider", "antigravity")
    return (configured, f"Default fallback provider: {configured}")
