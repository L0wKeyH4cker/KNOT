"""Real HTTP adapters: OpenAI Responses/Chat and Anthropic Messages.

References checked 2026-11-06:
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
https://platform.claude.com/docs/en/api/messages/create
Tool-loop compatibility checked 2026-11-07:
https://developers.openai.com/api/docs/guides/function-calling
https://api-docs.deepseek.com/guides/thinking_mode/
No provider errors ever fall back to mock output.
"""
from __future__ import annotations

import copy
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
    "quota": "API quota is exhausted or the spending limit has been reached. Check the balance and usage limits for your API project. Waiting and retrying will usually not fix this.",
    "rate_limit": "The request rate or token rate limit was exceeded. Try again later or reduce concurrency.",
    "authentication": "API authentication failed. Check that the local key is valid and belongs to the selected provider.",
    "permission": "The API denied access. Check the key's project, permissions, and access to the selected model.",
    "model": "The model or endpoint was not found, or this project cannot access it. Enter the provider's API model ID, rather than its display name, and check the base URL.",
    "invalid_request": "The API rejected the request parameters. Check the model ID, API compatibility, and base URL.",
    "server": "The model service is temporarily unavailable. Try again later.",
    "dns": "The model service hostname could not be resolved. Check your network, DNS, and base URL. No response was received from the model service.",
    "tls": "TLS certificate verification failed. Check your system certificates or network proxy; keep certificate verification enabled.",
    "timeout": "The model service connection or response timed out. Check your network and try again.",
    "network": "Could not connect to the model service. Check your network, proxy, firewall, and base URL. The key and model have not been verified.",
    "unknown_rate_limit": "The API returned HTTP 429 without a recognized error code. Check the provider console for quota or rate limits.",
    "http": "The model service rejected the request. Check the HTTP status and provider configuration.",
    "response": "The model call did not complete or returned an unusable response. Check model and API compatibility.",
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
        prefix = "(" + " / ".join(markers) + ") " if markers else ""
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


def _metered_post(url, headers, payload, timeout, callback, call_id, provider, protocol):
    """Persist usage before inspecting the response or executing its tools."""
    metadata = {"call_id": str(call_id), "provider": provider, "protocol": protocol,
                "model": payload.get("model", "")}
    if callback:
        callback({**metadata, "event": "request_started"})
    response = _post(url, headers, payload, timeout)
    if callback:
        callback({**metadata, "event": "response", "usage": response.get("usage"),
                  "response_id": response.get("id"), "model": response.get("model", metadata["model"])})
    return response


def _responses_complete(base, credential, model, system, prompt, tools, tool_executor,
                        deadline, max_tool_rounds, usage_callback=None):
    """Stateless Responses tool loop; reasoning stays only in provider context."""
    history = [{"role": "user", "content": prompt}]
    definitions = [{"type": "function", "name": item["name"], "description": item["description"],
                    "parameters": item["parameters"], "strict": False} for item in tools]
    allowed_names = {item["name"] for item in tools}
    seen_calls, usage = set(), []
    for round_number in range(max_tool_rounds + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Task model/tool deadline exceeded")
        payload = {"model": model, "instructions": system, "input": copy.deepcopy(history),
                   "tools": definitions, "store": False, "include": ["reasoning.encrypted_content"]}
        response = _metered_post(base + "/responses", {"Authorization": "Bearer " + credential}, payload,
                                 remaining, usage_callback, round_number + 1, "openai", "responses")
        if time.monotonic() >= deadline:
            raise TimeoutError("Task model/tool deadline exceeded")
        if response.get("status") != "completed" or response.get("error"):
            raise ProviderError("Responses request did not complete")
        if isinstance(response.get("usage"), dict):
            usage.append({"provider": "openai", **response["usage"]})
        output = response.get("output")
        if not isinstance(output, list):
            raise ProviderError("Responses returned invalid output")
        calls, texts, new_ids = [], [], set()
        # Validate every item before invoking any local tool in this response.
        for item in output:
            if not isinstance(item, dict) or item.get("status") in ("incomplete", "in_progress", "failed"):
                raise ProviderError("Responses returned an invalid or unfinished item")
            kind = item.get("type")
            if kind == "reasoning":
                continue
            if kind == "message":
                blocks = item.get("content")
                if item.get("role") != "assistant" or not isinstance(blocks, list):
                    raise ProviderError("Responses returned an invalid assistant message")
                for block in blocks:
                    if not isinstance(block, dict):
                        raise ProviderError("Responses returned invalid message content")
                    if block.get("type") == "refusal":
                        raise ProviderError("Model declined this request")
                    if block.get("type") != "output_text" or not isinstance(block.get("text"), str):
                        raise ProviderError("Responses returned unsupported message content")
                    texts.append(block["text"])
            elif kind == "function_call":
                call_id = item.get("call_id")
                if not isinstance(call_id, str) or not call_id or call_id in seen_calls or call_id in new_ids:
                    raise ProviderError("Responses returned a missing or duplicate tool call ID")
                if not isinstance(item.get("name"), str) or item["name"] not in allowed_names or tool_executor is None:
                    raise PermissionError("Only configured local function tools are supported")
                try:
                    arguments = json.loads(item["arguments"])
                except (KeyError, TypeError, ValueError):
                    raise ProviderError("Model returned malformed tool arguments") from None
                if not isinstance(arguments, dict):
                    raise ProviderError("Tool arguments must be a JSON object")
                new_ids.add(call_id)
                calls.append((item, arguments))
            else:
                raise ProviderError("Responses returned an unsupported output item")
        if not calls:
            content = "\n".join(texts)
            if not content.strip():
                raise ProviderError("Responses returned no usable text")
            return _parse_result(content, usage)
        if round_number >= max_tool_rounds:
            raise ProviderError("Maximum tool-call rounds exceeded")
        if len(calls) > 16:
            raise ProviderError("Too many tool calls in one model round")
        # Retain reasoning (including encrypted state), messages and call items
        # exactly for continuation, without storing or returning them to the app.
        history.extend(copy.deepcopy(output))
        seen_calls.update(new_ids)
        for call, arguments in calls:
            if time.monotonic() >= deadline:
                raise TimeoutError("Task model/tool deadline exceeded")
            result = tool_executor(call["name"], arguments)
            history.append({"type": "function_call_output", "call_id": call["call_id"],
                            "output": json.dumps(redact(result), ensure_ascii=False)})
    raise ProviderError("Maximum model rounds exceeded")


def complete(agent: dict, system: str, prompt: str, tools: list[dict] | None = None,
             tool_executor: Callable[[str, dict], Any] | None = None,
             timeout: float = 60, max_tool_rounds: int = 4, usage_callback: Callable | None = None) -> dict:
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
    if provider == "openai" and parsed.hostname == "api.openai.com" and model.startswith("gpt-6") and tools:
        return _responses_complete(base, credential, model, system, prompt, tools,
                                   tool_executor, deadline, max_tool_rounds, usage_callback)
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
            if agent.get("thinking") == "disabled" and parsed.hostname == "api.deepseek.com":
                # Structured planning output does not need DeepSeek's slow thinking mode.
                # https://api-docs.deepseek.com/guides/thinking_mode/
                payload["thinking"] = {"type": "disabled"}
            if tools:
                payload["tools"] = [{"type": "function", "function": item} for item in tools]
            response = _metered_post(base + "/chat/completions", {"Authorization": "Bearer " + credential}, payload,
                                     remaining, usage_callback, round_number + 1, provider, "chat")
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
            assistant = {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
            # Thinking-enabled compatible providers require this on tool-loop
            # continuation. It remains request-local and is never a result/log.
            if isinstance(message.get("reasoning_content"), str):
                assistant["reasoning_content"] = message["reasoning_content"]
            messages.append(assistant)
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
            response = _metered_post(base + "/messages", {"x-api-key": credential, "anthropic-version": "2023-06-01"}, payload,
                                     remaining, usage_callback, round_number + 1, provider, "messages")
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
