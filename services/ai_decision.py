"""Server-side AI helpers for decision evidence and score drafts."""

import json
import os
from typing import Any


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def get_ai_enabled() -> bool:
    return _env_bool("AI_ENABLED", False) and bool(get_openai_api_key())


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL


def get_openai_api_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY")
    return key.strip() if key and key.strip() else None


def get_ai_caps() -> dict[str, int]:
    return {
        "max_metric_suggestions": _env_int("AI_MAX_METRIC_SUGGESTIONS", 8),
        "max_score_drafts_per_request": _env_int("AI_MAX_SCORE_DRAFTS_PER_REQUEST", 100),
        "max_evidence_items_per_request": _env_int("AI_MAX_EVIDENCE_ITEMS_PER_REQUEST", 100),
    }


def ai_status() -> dict[str, Any]:
    configured = bool(get_openai_api_key())
    enabled_flag = _env_bool("AI_ENABLED", False)
    enabled = configured and enabled_flag
    reason = "available" if enabled else "disabled"
    if enabled_flag and not configured:
        reason = "missing_openai_api_key"
    return {
        "enabled": enabled,
        "provider": "openai",
        "model": get_openai_model(),
        "reason": reason,
        "caps": get_ai_caps(),
    }


class AIUnavailableError(RuntimeError):
    pass


class AIProviderOutputError(RuntimeError):
    pass


class OpenAIDecisionClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or get_openai_api_key()
        self.model = model or get_openai_model()

    def structured_json(self, prompt: str) -> dict[str, Any]:
        if not get_ai_enabled() or not self.api_key:
            raise AIUnavailableError("AI is disabled")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIUnavailableError("OpenAI SDK is not installed") from exc

        try:
            client = OpenAI(api_key=self.api_key, timeout=120.0)
            response = client.responses.create(
                model=self.model,
                input=prompt,
                text={"format": {"type": "json_object"}},
            )
        except Exception as exc:
            raise AIUnavailableError(f"AI provider error: {exc}") from exc

        text = getattr(response, "output_text", None)
        if not text:
            raise AIProviderOutputError("Malformed AI output")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIProviderOutputError("Malformed AI output") from exc
        if not isinstance(parsed, dict):
            raise AIProviderOutputError("Malformed AI output")
        return parsed


def build_decision_context(
    decision,
    activities: list,
    metrics: list,
    user_context: str = "",
    instruction: str | None = None,
) -> str:
    ctx = {
        "decision": {"id": decision.id, "query": decision.query},
        "activities": [{"id": a.id, "name": a.name} for a in activities],
        "metrics": [{"id": m.id, "name": m.name, "description": m.description or ""} for m in metrics],
        "user_context": user_context[:4000],
    }
    if instruction:
        ctx["instruction"] = instruction
    return json.dumps(ctx)
