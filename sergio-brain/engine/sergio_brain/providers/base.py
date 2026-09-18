from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass

from ..config import Config
from ..db import Database


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = ""
    model: str = ""
    ok: bool = True
    error: str = ""


class CostTracker:
    def __init__(self, db: Database, cfg: Config):
        self.db = db
        self.cfg = cfg

    def record(self, provider: str, model: str, kind: str, result: LLMResult, duration_ms: int) -> None:
        cost = (result.input_tokens * self.cfg.ai.cost_input_per_million
                + result.output_tokens * self.cfg.ai.cost_output_per_million) / 1_000_000
        self.db.execute(
            "INSERT INTO ai_calls(provider, model, kind, input_tokens, output_tokens, estimated_cost, success, error, duration_ms, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (provider, model, kind, result.input_tokens, result.output_tokens, cost, 1 if result.ok else 0,
             (result.error or "")[:500], duration_ms, time.time()))

    def summary(self, days: int = 30) -> dict:
        since = time.time() - days * 86400
        row = self.db.one(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(input_tokens),0) AS input_tokens, COALESCE(SUM(output_tokens),0) AS output_tokens,"
            " COALESCE(SUM(estimated_cost),0) AS estimated_cost, COALESCE(SUM(CASE WHEN success=0 THEN 1 ELSE 0 END),0) AS failed"
            " FROM ai_calls WHERE created_at>=?", (since,))
        return dict(row) if row else {}


class LLMProvider:
    name = "base"
    model = ""
    cloud = False

    def available(self) -> bool:
        return True

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        raise NotImplementedError


class NoneProvider(LLMProvider):
    """No LLM configured. The system still works: retrieval, extraction and reports are heuristic."""

    name = "none"
    cloud = False

    def available(self) -> bool:
        return False

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        return LLMResult(text="", ok=False, error="No LLM provider configured", provider="none")


class ClaudeProvider(LLMProvider):
    name = "claude"
    cloud = True

    def __init__(self, model: str):
        self.model = model
        self._client = None

    def available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        try:
            import anthropic
            client = self._get_client()
            with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                resp = stream.get_final_message()
            if resp.stop_reason == "refusal":
                return LLMResult(text="", ok=False, error="model refused the request", provider=self.name, model=self.model,
                                 input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return LLMResult(text=text, input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                             provider=self.name, model=self.model)
        except Exception as exc:  # noqa: BLE001 - surfaced to caller, data is never lost
            return LLMResult(text="", ok=False, error=f"{type(exc).__name__}: {exc}", provider=self.name, model=self.model)


class OpenAIProvider(LLMProvider):
    name = "openai"
    cloud = True

    def __init__(self, model: str):
        self.model = model

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        key = os.environ.get("OPENAI_API_KEY", "")
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
            usage = data.get("usage", {})
            return LLMResult(text=data["choices"][0]["message"]["content"], input_tokens=usage.get("prompt_tokens", 0),
                             output_tokens=usage.get("completion_tokens", 0), provider=self.name, model=self.model)
        except Exception as exc:  # noqa: BLE001
            return LLMResult(text="", ok=False, error=f"{type(exc).__name__}: {exc}", provider=self.name, model=self.model)


class OllamaProvider(LLMProvider):
    name = "ollama"
    cloud = False

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=2) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        body = {"model": self.model, "stream": False, "system": system, "prompt": user,
                "options": {"num_predict": max_tokens}}
        req = urllib.request.Request(self.url + "/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = json.loads(r.read())
            return LLMResult(text=data.get("response", ""), input_tokens=data.get("prompt_eval_count", 0),
                             output_tokens=data.get("eval_count", 0), provider=self.name, model=self.model)
        except Exception as exc:  # noqa: BLE001
            return LLMResult(text="", ok=False, error=f"{type(exc).__name__}: {exc}", provider=self.name, model=self.model)


def build_llm_provider(cfg: Config) -> LLMProvider:
    mode = cfg.ai.mode.upper()
    name = cfg.ai.llm_provider.lower()
    if name == "claude":
        p: LLMProvider = ClaudeProvider(cfg.ai.llm_model)
    elif name == "openai":
        p = OpenAIProvider(cfg.ai.openai_model)
    elif name == "ollama":
        p = OllamaProvider(cfg.ai.ollama_url, cfg.ai.ollama_model)
    else:
        return NoneProvider()
    if p.cloud and mode == "LOCAL_ONLY":
        return NoneProvider()
    return p
