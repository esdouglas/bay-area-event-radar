"""Model-independent LLM client with cost accounting.

Providers are selected by environment, so the collection infrastructure never depends on one vendor:
  RADAR_LLM_PROVIDER = anthropic | openai | none   (default: anthropic if ANTHROPIC_API_KEY is set,
                                                     openai if OPENAI_API_KEY is set, else none)
  RADAR_LLM_FAST  / RADAR_LLM_SMART = model ids for cheap classification vs deeper research.
Every call appends {provider, model, in_tokens, out_tokens, usd, purpose} to data/costs.jsonl.
"""
import json
import os
import re
import time

import requests

from . import config, store

# USD per million tokens (input, output). Verified against platform.claude.com/docs/en/models/overview
# on 2026-10-25; OpenAI figures are placeholders to be set by whoever enables that provider.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}
DEFAULTS = {
    "anthropic": {"fast": "claude-haiku-5-5", "smart": "claude-sonnet-5-5"},
    "openai": {"fast": "gpt-4o-mini", "smart": "gpt-4o"},
}


def provider() -> str:
    p = os.environ.get("RADAR_LLM_PROVIDER", "").strip().lower()
    if p:
        return p
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "none"


def available() -> bool:
    return provider() in ("anthropic", "openai")


def model_for(tier: str) -> str:
    env = os.environ.get("RADAR_LLM_FAST" if tier == "fast" else "RADAR_LLM_SMART")
    return env or DEFAULTS.get(provider(), DEFAULTS["anthropic"])[tier]


class LLMError(Exception):
    pass


def complete(system: str, user: str, *, tier: str = "fast", max_tokens: int = 2000, purpose: str = "",
             json_mode: bool = True, temperature: float = 0.0, retries: int = 2) -> str:
    """Return the model's text. With json_mode the text is expected to be a single JSON value."""
    p = provider()
    if p == "none":
        raise LLMError("no LLM provider configured")
    model = model_for(tier)
    last = None
    for attempt in range(retries + 1):
        try:
            if p == "anthropic":
                text, usage = _anthropic(system, user, model, max_tokens, temperature)
            elif p == "openai":
                text, usage = _openai(system, user, model, max_tokens, temperature, json_mode)
            else:
                raise LLMError(f"unknown provider {p}")
            _record(p, model, usage, purpose)
            return text
        except (requests.RequestException, LLMError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise LLMError(f"LLM call failed after retries: {last}")


def _anthropic(system, user, model, max_tokens, temperature):
    key = os.environ["ANTHROPIC_API_KEY"]
    body = {"model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]}
    r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=180,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    if r.status_code >= 400:
        raise LLMError(f"anthropic HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    u = d.get("usage", {})
    return text, {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0)}


def _openai(system, user, model, max_tokens, temperature, json_mode):
    key = os.environ["OPENAI_API_KEY"]
    body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://api.openai.com/v1/chat/completions", json=body, timeout=180,
                      headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
    if r.status_code >= 400:
        raise LLMError(f"openai HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()
    u = d.get("usage", {})
    return d["choices"][0]["message"]["content"], {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}


def _record(p, model, usage, purpose):
    pin, pout = PRICES.get(model, (0.0, 0.0))
    usd = usage["in"] / 1e6 * pin + usage["out"] / 1e6 * pout
    store.append_cost({"ts": config.now_iso(), "provider": p, "model": model, "in_tokens": usage["in"],
                       "out_tokens": usage["out"], "usd": round(usd, 6), "purpose": purpose})


def parse_json(text: str):
    """Tolerant JSON extraction: strips code fences and leading prose."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def cost_summary(days: int = 30) -> dict:
    if not config.COSTS_FILE.exists():
        return {"usd": 0.0, "calls": 0, "by_purpose": {}}
    cutoff = (config.now_utc().timestamp() - days * 86400)
    total = 0.0
    calls = 0
    by = {}
    with open(config.COSTS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts", "")
            try:
                import datetime as dt
                t = dt.datetime.fromisoformat(ts).timestamp()
            except ValueError:
                t = 0
            if t < cutoff:
                continue
            total += rec.get("usd", 0)
            calls += 1
            b = by.setdefault(rec.get("purpose", "?"), {"usd": 0.0, "calls": 0})
            b["usd"] += rec.get("usd", 0)
            b["calls"] += 1
    return {"usd": round(total, 4), "calls": calls, "by_purpose": {k: {"usd": round(v["usd"], 4), "calls": v["calls"]} for k, v in by.items()}}
