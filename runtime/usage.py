"""Per-attempt usage records. Estimates are never confirmed charges."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .activity import sanitize_text

MAX_TOKENS = 9_007_199_254_740_991
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_creation_input_tokens")
REPORT_FIELDS = ("id", "run_id", "node_id", "node_label", "agent_id", "agent_name", "owner_id",
                 "owner_name", "provider", "model", "attempt", "status", "usage_status",
                 "usage", "started_at", "updated_at")


def token(value):
    return value if type(value) is int and 0 <= value <= MAX_TOKENS else None


def _sum_known(values):
    return token(sum(values)) if values and all(value is not None for value in values) else None


def normalized_usage(value, protocol):
    value = value if isinstance(value, dict) else {}
    result = dict.fromkeys(TOKEN_FIELDS)
    if protocol in ("messages", "claude"):
        cached = token(value.get("cache_read_input_tokens"))
        creation = token(value.get("cache_creation_input_tokens"))
        result.update(input_tokens=_sum_known([token(value.get("input_tokens")), cached, creation]),
                      cached_input_tokens=cached, cache_creation_input_tokens=creation)
    elif protocol == "chat":
        details = value.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        result.update(input_tokens=token(value.get("prompt_tokens")),
                      cached_input_tokens=token(details.get("cached_tokens", value.get("prompt_cache_hit_tokens"))),
                      cache_creation_input_tokens=token(details.get("cache_write_tokens")))
    else:
        details = value.get("input_tokens_details")
        details = details if isinstance(details, dict) else {}
        result.update(input_tokens=token(value.get("input_tokens")),
                      cached_input_tokens=token(value.get("cached_input_tokens", details.get("cached_tokens"))),
                      cache_creation_input_tokens=token(value.get("cache_write_input_tokens", details.get("cache_write_tokens"))))
    result["output_tokens"] = token(value.get("completion_tokens") if protocol == "chat" else value.get("output_tokens"))
    total = result["input_tokens"]
    cached = result["cached_input_tokens"]
    creation = result["cache_creation_input_tokens"]
    if total is not None and ((cached is not None and cached > total)
                              or (creation is not None and creation > total)
                              or (cached is not None and creation is not None and cached + creation > total)):
        # Preserve the reported total but discard an impossible breakdown.
        # The marker is internal only and never enters the exported usage object.
        result["cached_input_tokens"] = result["cache_creation_input_tokens"] = None
        result["_invalid"] = True
    return result


def estimated_usd(value):
    # Only an explicit CLI accounting field reaches here, never model content.
    if type(value) not in (int, float, str):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount >= Decimal("1000000000000"):
            return None
        rounded = amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if rounded >= Decimal("1000000000000"):
            return None
        return format(rounded, "f")
    except (InvalidOperation, ValueError):
        return None


def new_entry(state, workflow, node, attempt, mode, execution, timestamp, *, legacy=False):
    cfg = node["config"]
    agent = next((a for a in workflow["agents"] if a["id"] == cfg.get("agent_id")), {})
    member = next((m for m in workflow["project"]["members"] if m["id"] == cfg.get("owner_id")), {})
    entry = {"id": f"{state['run_id']}:{node['id']}:{'legacy' if legacy else attempt}",
             "run_id": state["run_id"], "node_id": node["id"], "node_label": node["label"],
             "agent_id": agent.get("id", ""), "agent_name": agent.get("name", ""),
             "owner_id": member.get("id", ""), "owner_name": member.get("name", ""),
             "provider": execution["backend"] if execution else agent.get("provider", ""),
             "model": execution["model"] if execution else agent.get("model", ""),
             "attempt": attempt, "status": "unknown" if legacy else "running",
             "usage_status": "legacy" if legacy else "simulated" if mode == "mock" else "unknown",
             "usage": dict.fromkeys(TOKEN_FIELDS), "started_at": timestamp, "updated_at": timestamp,
             "calls": {}}
    # IDs already pass workflow validation; display sanitization must not alter
    # a stable key such as "run:token:1" into a different identifier.
    for key in ("node_label", "agent_name", "owner_name", "model"):
        entry[key] = sanitize_text(entry[key], 300)
    return entry


def record_event(entry, event, timestamp):
    """Request snapshots replace their own record; cumulative CLI is one call."""
    call_id = str(event.get("call_id", "cli"))
    calls = entry.setdefault("calls", {})
    call = calls.setdefault(call_id, {"received": False, "usage": dict.fromkeys(TOKEN_FIELDS)})
    if event.get("event") in ("response", "terminal"):
        call["received"] = True
        reported = normalized_usage(event.get("usage"), event.get("protocol"))
        call["usage"] = {field: reported[field] if reported[field] is not None else call["usage"].get(field)
                         for field in TOKEN_FIELDS}
        if reported.get("_invalid"):
            call["usage"]["cached_input_tokens"] = call["usage"]["cache_creation_input_tokens"] = None
        call["complete"] = (not reported.get("_invalid") and reported["input_tokens"] is not None
                            and reported["output_tokens"] is not None)
        if isinstance(event.get("response_id"), str):
            call["response_id"] = sanitize_text(event["response_id"], 200)
        if isinstance(event.get("model"), str) and event["model"].strip():
            call["model"] = sanitize_text(event["model"], 200)
            models = {item.get("model") for item in calls.values() if item.get("model")}
            entry["model"] = next(iter(models)) if len(models) == 1 else "multiple"
        # An explicit zero on an error terminal is not evidence of zero spend.
        if event.get("protocol") == "claude":
            amount = estimated_usd(event.get("estimated_cost_usd"))
            if amount is not None and (Decimal(amount) > 0 or event.get("terminal_success") is True):
                entry["estimated_cost"] = {"amount": amount, "currency": "USD", "source": "Claude CLI estimate"}
    for field in TOKEN_FIELDS:
        values = [item["usage"].get(field) for item in calls.values()]
        known = [value for value in values if value is not None]
        # This is the known subtotal when some calls did not report a field.
        entry["usage"][field] = token(sum(known)) if known else None
    any_usage = any(value is not None for value in entry["usage"].values())
    complete = (all(item.get("received") and item.get("complete") for item in calls.values())
                and entry["usage"]["input_tokens"] is not None and entry["usage"]["output_tokens"] is not None)
    # A breakdown reported by only some calls is a subtotal, not a complete
    # cache count. All-null optional breakdowns remain explicitly unavailable.
    for field in TOKEN_FIELDS:
        known = [item["usage"].get(field) is not None for item in calls.values()]
        if any(known) and not all(known):
            complete = False
    entry["usage_status"] = "reported" if complete else "partial" if any_usage else "unknown"
    entry["updated_at"] = timestamp


def usage_report(state, workflow):
    entries = []
    for entry in state.get("usage_ledger", {}).values():
        public = {field: entry[field] for field in REPORT_FIELDS}
        if "estimated_cost" in entry:
            public["estimated_cost"] = entry["estimated_cost"]
        entries.append(public)
    return {"kind": "knot-usage", "schema_version": "1.0",
            "project": {"id": workflow["project"]["id"], "name": sanitize_text(workflow["project"]["name"], 300)},
            "run_id": state["run_id"], "updated_at": state["updated_at"], "entries": entries}
