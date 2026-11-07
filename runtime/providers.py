"""Real HTTP adapters: OpenAI Chat Completions and Anthropic Messages.

References checked 2026-11-06:
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
https://platform.claude.com/docs/en/api/messages/create
No provider errors ever fall back to mock output.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from .security import ENV_RE, redact, register_secret


SAFE_ERROR_CODES = {
    "insufficient_quota", "billing_hard_limit_reached", "spend_limit_reached", "usage_limit_reached",
    "rate_limit_exceeded", "invalid_api_key", "authentication_error", "permission_denied",
    "permission_error", "model_not_found", "not_found_error", "invalid_request_error",
    "invalid_value", "unsupported_value", "server_error", "api_error", "overloaded_error",
}
SAFE_ERROR_TYPES = {
    "insufficient_quota", "rate_limit_error", "rate_limit_exceeded", "authentication_error",
    "permission_error", "not_found_error", "invalid_request_error", "server_error",
    "api_error", "overloaded_error",
}
PUBLIC_ERROR_MESSAGES = {
    "quota": "API 额度不足，或已达到消费上限。请检查该 API 项目的余额与使用限额；稍后重试通常不能解决。",
    "rate_limit": "请求频率或 token 速率超过限制。请稍后重试，或降低并发数量。",
    "authentication": "API 认证失败。请检查本地 key 是否有效，以及它是否属于当前服务商。",
    "permission": "API 拒绝访问。请检查 key 所属项目、权限范围及模型访问权限。",
    "model": "找不到模型或接口，或当前项目无权访问。请填写服务商提供的 API 模型 ID（不是显示名称），并核对 Base URL。",
    "invalid_request": "API 不接受当前请求参数。请核对模型 ID、接口兼容性与 Base URL。",
    "server": "模型服务暂时不可用。请稍后重试。",
    "dns": "无法解析模型服务域名，请检查网络、DNS 和 Base URL。请求尚未收到模型服务响应。",
    "tls": "模型服务的 TLS 证书校验失败。请检查本机证书或网络代理，不要关闭证书校验。",
    "timeout": "模型服务连接或响应超时。请检查网络后重试。",
    "network": "无法连接模型服务，请检查网络、代理、防火墙与 Base URL。尚不能判断 key 或模型是否有效。",
    "unknown_rate_limit": "API 返回 429，但没有可识别的错误代码。可能是额度不足或频率限制，请检查服务商控制台。",
    "http": "模型服务拒绝了请求。请根据 HTTP 状态检查服务商配置。",
    "response": "模型调用未完成或响应格式无法使用。请检查模型与接口兼容性。",
}


def _error_category(status, code, error_type):
    tokens = {code, error_type}
    if status == 402 or tokens & {"insufficient_quota", "billing_hard_limit_reached", "spend_limit_reached", "usage_limit_reached"}:
        return "quota"
    if tokens & {"rate_limit_exceeded", "rate_limit_error"}:
        return "rate_limit"
    if status == 401 or tokens & {"invalid_api_key", "authentication_error"}:
        return "authentication"
    if status == 403 or tokens & {"permission_denied", "permission_error"}:
        return "permission"
    if status == 404 or tokens & {"model_not_found", "not_found_error"}:
        return "model"
    if status == 429:
        return "unknown_rate_limit"
    if status is not None and status >= 500:
        return "server"
    if status in (400, 422):
        return "invalid_request"
    return "http" if status is not None else "response"


class ProviderError(RuntimeError):
    """Safe diagnostics; raw provider messages, URLs and request bodies stay private."""

    def __init__(self, message, *, http_status=None, error_code=None, error_type=None, category=None):
        super().__init__(redact(str(message)))
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.error_code = error_code if isinstance(error_code, str) and error_code in SAFE_ERROR_CODES else None
        self.error_type = error_type if isinstance(error_type, str) and error_type in SAFE_ERROR_TYPES else None
        self.category = category if category in PUBLIC_ERROR_MESSAGES else _error_category(self.http_status, self.error_code, self.error_type)

    def user_message(self):
        markers = []
        if self.http_status is not None:
            markers.append(f"HTTP {self.http_status}")
        if self.error_code:
            markers.append(self.error_code)
        elif self.error_type:
            markers.append(self.error_type)
        prefix = "（" + " / ".join(markers) + "）" if markers else ""
        return prefix + PUBLIC_ERROR_MESSAGES[self.category]


def _read_bounded(response, deadline, limit):
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Provider response deadline exceeded")
        # HTTPError wraps an HTTPResponse, so its socket is one level deeper.
        # Apply the same remaining-time limit on error bodies and successful ones.
        for stream in (response, getattr(response, "fp", None)):
            connection = getattr(getattr(getattr(stream, "fp", None), "raw", None), "_sock", None)
            if connection is not None:
                connection.settimeout(max(0.01, remaining))
                break
        chunk = response.read1(min(65_536, limit + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise ValueError("Provider response body limit exceeded")
    if time.monotonic() > deadline:
        raise TimeoutError("Provider request deadline exceeded")
    return b"".join(chunks)


def _http_error(error, deadline):
    code = error_type = None
    try:
        with error:
            payload = json.loads(_read_bounded(error, deadline, 65_536))
        detail = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            # Only enum-like values from explicit allowlists may cross this boundary.
            candidate = detail.get("code")
            if isinstance(candidate, str) and candidate in SAFE_ERROR_CODES:
                code = candidate
            candidate = detail.get("type")
            if isinstance(candidate, str) and candidate in SAFE_ERROR_TYPES:
                error_type = candidate
    except (ValueError, UnicodeError, OSError, AttributeError):
        # A malformed/large/slow error body must not hide the known HTTP status.
        pass
    suffix = f" ({code or error_type})" if code or error_type else ""
    return ProviderError(f"Provider HTTP {error.code}{suffix}", http_status=error.code, error_code=code, error_type=error_type)


def _transport_error(error):
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, socket.gaierror):
        category = "dns"
    elif isinstance(cause, ssl.SSLError):
        category = "tls"
    elif isinstance(cause, TimeoutError):
        category = "timeout"
    else:
        category = "network"
    return ProviderError(f"Provider request failed: {category}", category=category)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("Provider redirects are disabled to protect credentials")


def _post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=max(0.01, timeout)) as response:
            raw = _read_bounded(response, deadline, 8_000_000)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ProviderError("Provider returned a non-object response")
        return result
    except urllib.error.HTTPError as error:
        raise _http_error(error, deadline) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise _transport_error(error) from None
    except (ValueError, UnicodeError):
        raise ProviderError("Provider returned invalid JSON") from None


def _parse_result(content: str, usage: list[dict]) -> dict:
    clean = content.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines[-1].strip() == "```":
            clean = "\n".join(lines[1:-1])
    try:
        data = json.loads(clean)
    except (ValueError, TypeError):
        data = None
    return redact({"content": content, "data": data, "usage": usage})


def complete(agent: dict, system: str, prompt: str, tools: list[dict] | None = None,
             tool_executor: Callable[[str, dict], Any] | None = None,
             timeout: float = 60, max_tool_rounds: int = 4) -> dict:
    """One isolated conversation, with a bounded tool loop and overall deadline."""
    provider = agent.get("provider")
    if provider not in ("openai", "anthropic"):
        raise ProviderError("Unsupported provider; choose openai or anthropic")
    model = agent.get("model", "")
    if not isinstance(model, str) or not model.strip():
        raise ProviderError("A model name is required for real mode")
    ref = agent.get("credential_ref", "")
    if not isinstance(ref, str) or not ENV_RE.fullmatch(ref):
        raise ProviderError("credential_ref must name an environment variable")
    credential = os.environ.get(ref, "").strip()
    if not credential:
        raise ProviderError(f"Missing credential environment variable: {ref}; real mode does not fall back to mock")
    register_secret(credential)
    default = "https://api.openai.com/v1" if provider == "openai" else "https://api.anthropic.com/v1"
    base = (agent.get("base_url") or default).rstrip("/")
    parsed = urlparse(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or not (parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ProviderError("Provider base_url must use HTTPS or loopback HTTP without credentials")
    tools = tools or []
    deadline = time.monotonic() + timeout
    usage = []
    messages = [{"role": "user", "content": prompt}]
    if provider == "openai":
        messages.insert(0, {"role": "system", "content": system})
    for round_number in range(max_tool_rounds + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Task model/tool deadline exceeded")
        if provider == "openai":
            payload = {"model": model, "messages": messages}
            if tools:
                payload["tools"] = [{"type": "function", "function": item} for item in tools]
            response = _post(base + "/chat/completions", {"Authorization": "Bearer " + credential}, payload, remaining)
            if isinstance(response.get("usage"), dict):
                usage.append({"provider": provider, **response["usage"]})
            try:
                choice = response["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError):
                raise ProviderError("OpenAI response did not contain a completion") from None
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise ProviderError(f"OpenAI completion stopped: {choice['finish_reason']}")
            if message.get("refusal"):
                raise ProviderError("Model declined this request")
            calls = message.get("tool_calls") or []
            if not calls:
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ProviderError("OpenAI returned no usable text")
                return _parse_result(content, usage)
            if round_number >= max_tool_rounds:
                raise ProviderError("Maximum tool-call rounds exceeded")
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
            if len(calls) > 16:
                raise ProviderError("Too many tool calls in one model round")
            for call in calls:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Task model/tool deadline exceeded")
                if call.get("type") != "function" or tool_executor is None:
                    raise PermissionError("Only configured local function tools are supported")
                function = call.get("function", {})
                try:
                    args = json.loads(function.get("arguments", "{}"))
                except ValueError:
                    raise ProviderError("Model returned malformed tool arguments") from None
                output = tool_executor(function.get("name", ""), args)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(redact(output), ensure_ascii=False)})
        else:
            payload = {"model": model, "system": system, "messages": messages, "max_tokens": 8192}
            if tools:
                payload["tools"] = [{"name": item["name"], "description": item["description"], "input_schema": item["parameters"]} for item in tools]
            response = _post(base + "/messages", {"x-api-key": credential, "anthropic-version": "2023-06-01"}, payload, remaining)
            if isinstance(response.get("usage"), dict):
                usage.append({"provider": provider, **response["usage"]})
            blocks = response.get("content")
            if not isinstance(blocks, list):
                raise ProviderError("Anthropic response did not contain content blocks")
            if response.get("stop_reason") in ("max_tokens", "refusal", "pause_turn"):
                raise ProviderError(f"Anthropic completion stopped: {response['stop_reason']}")
            calls = [block for block in blocks if block.get("type") == "tool_use"]
            if not calls:
                content = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text")
                if not content.strip():
                    raise ProviderError("Anthropic returned no usable text")
                return _parse_result(content, usage)
            if round_number >= max_tool_rounds:
                raise ProviderError("Maximum tool-call rounds exceeded")
            if len(calls) > 16:
                raise ProviderError("Too many tool calls in one model round")
            messages.append({"role": "assistant", "content": blocks})
            tool_results = []
            for call in calls:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Task model/tool deadline exceeded")
                if tool_executor is None:
                    raise PermissionError("Tool execution was not enabled")
                output = tool_executor(call.get("name", ""), call.get("input", {}))
                tool_results.append({"type": "tool_result", "tool_use_id": call["id"], "content": json.dumps(redact(output), ensure_ascii=False)})
            messages.append({"role": "user", "content": tool_results})
    raise ProviderError("Maximum model rounds exceeded")
