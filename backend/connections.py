"""Local credential setup and bounded provider connection checks."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlsplit

from backend.planner import PlanningError, build_planner_agent
from runtime.providers import ProviderError, _post
from runtime.security import ENV_RE, register_secret

_LOCK = threading.RLock()
KNOWN_REFS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"}
DEEPSEEK_CONNECTION = {
    "provider": "openai", "model": "deepseek-flash",
    "credential_ref": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com",
}


def credential_status(root: Path) -> dict:
    refs = set(KNOWN_REFS)
    with _LOCK:
        for filename in (".env.local", ".env"):
            path = root / filename
            if path.is_file() and not path.is_symlink():
                for line in path.read_text(encoding="utf-8-sig").splitlines():
                    ref = line.partition("=")[0].strip()
                    if ENV_RE.fullmatch(ref) and ref.endswith(("_KEY", "_TOKEN", "_SECRET")):
                        refs.add(ref)
        return {ref: bool(os.environ.get(ref, "").strip()) for ref in sorted(refs)}


def save_credential(root: Path, ref, value) -> dict:
    if not isinstance(ref, str) or not ENV_RE.fullmatch(ref) or not ref.endswith(("_KEY", "_TOKEN", "_SECRET")):
        raise PlanningError("凭证名称必须是以 _KEY、_TOKEN 或 _SECRET 结尾的大写环境变量名。")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{8,4096}", value):
        raise PlanningError("请输入有效的 API Key，不要包含空格或换行。")
    path = root / ".env.local"
    with _LOCK:
        if path.is_symlink():
            raise PlanningError("无法保存到符号链接形式的配置文件。")
        lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
        lines = [line for line in lines if line.partition("=")[0].strip() != ref]
        lines.append(f"{ref}={value}")
        descriptor, temporary = tempfile.mkstemp(prefix=".env.local.", dir=root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write("\n".join(lines) + "\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        register_secret(value)
        os.environ[ref] = value
        return credential_status(root)


def test_connection(connection) -> dict:
    agent = build_planner_agent(connection)
    provider = agent["provider"]
    default = "https://api.openai.com/v1" if provider == "openai" else "https://api.anthropic.com/v1"
    base = agent.get("base_url") or default
    if not isinstance(base, str):
        raise PlanningError("API 地址必须是文本。")
    base = base.rstrip("/")
    try:
        parsed = urlsplit(base)
        port = parsed.port
    except ValueError:
        raise PlanningError("API 地址格式无效。") from None
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or not (
        parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    ) or port == 0:
        raise PlanningError("API 地址必须是 HTTPS，或本机的 HTTP 地址，且不能含有凭证。")
    key = os.environ[agent["credential_ref"]].strip()
    register_secret(key)
    payload = {"model": agent["model"], "max_tokens": 16, "messages": [{"role": "user", "content": "Reply with OK."}]}
    if provider == "openai" and parsed.hostname == "api.openai.com":
        # Official reasoning models use the completion budget for both reasoning
        # and visible text. Astra does not support disabling reasoning entirely.
        # https://developers.openai.com/api/docs/guides/latest-model
        del payload["max_tokens"]
        payload["max_completion_tokens"] = 512
        if agent["model"].startswith("gpt-6"):
            payload["reasoning_effort"] = "low"
    elif provider == "openai" and parsed.hostname == "api.deepseek.com":
        payload["thinking"] = {"type": "disabled"}
    headers = {"Authorization": "Bearer " + key} if provider == "openai" else {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        response = _post(base + ("/chat/completions" if provider == "openai" else "/messages"), headers, payload, 30)
        _validate_connection_response(response, provider)
    except ProviderError as exc:
        raise PlanningError("连接测试失败：" + exc.user_message(), status=502) from None
    return {"ok": True, "model": agent["model"], "message": "Connection verified. The model accepted a test request."}


def _validate_connection_response(response, provider):
    """A 200 response alone does not prove the configured model can answer."""
    if not isinstance(response, dict) or response.get("error"):
        raise ProviderError("Invalid connection check response")
    if provider == "openai":
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProviderError("No completion in connection check response")
        choice = choices[0]
        message = choice.get("message")
        if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
            raise ProviderError("Connection check did not finish normally")
        if message.get("refusal") or message.get("tool_calls") or message.get("function_call"):
            raise ProviderError("Connection check did not return a text answer")
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("No usable text in connection check response")
    else:
        content = response.get("content")
        if response.get("stop_reason") not in ("end_turn", "stop_sequence") or not isinstance(content, list) or not content:
            raise ProviderError("Connection check did not finish normally")
        if any(not isinstance(block, dict) or block.get("type") != "text" or
               not isinstance(block.get("text"), str) for block in content):
            raise ProviderError("Connection check did not return a text answer")
        if not any(block["text"].strip() for block in content):
            raise ProviderError("No usable text in connection check response")
