"""The Model Layer — one common switch for any LLM (doc §8).

Agents always talk to this layer; the layer talks to whichever provider the
.env selects (LLM_PROVIDER=gemini today, claude later — a one-line change).

Also implements the §11.5 controls: model tiers (fast vs strong), a global
concurrency limit sized to provider rate limits, retry with exponential
backoff on 429/5xx, and per-organisation monthly budgets with usage tracking.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import func, select

from app.config import get_settings
from app.core.exceptions import BudgetExceededError, ExternalServiceError

logger = logging.getLogger(__name__)

# Approximate USD per 1M tokens (input, output) — used for budget tracking.
# Keys are matched against the model id EXACTLY; anything missing falls back to
# (0.5, 1.5) below, so an id that is absent here is silently mis-billed. The
# OpenRouter ids carry their provider prefix and must be listed in that form.
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    # OpenRouter ids (prices read live from GET /api/v1/models, 2026-07-22).
    # Without these the default (0.5, 1.5) over-bills gpt-5.4-nano's input by
    # 2.5x, which would trip the per-org budget guard early.
    "openai/gpt-5.4-nano": (0.20, 1.25),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
}

TIER_FAST = "fast"
TIER_STRONG = "strong"


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str = ""


@dataclass
class LlmResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# Neutral message format understood by every provider adapter:
#   {"role": "user" | "assistant", "content": "..."}
#   {"role": "assistant", "tool_calls": [ToolCall, ...]}
#   {"role": "tool_result", "name": "...", "call_id": "...", "result": {...}}
Message = dict[str, Any]

_semaphore: asyncio.Semaphore | None = None
# Fire-and-forget tasks need a strong reference or the event loop may GC
# them mid-flight (usage rows would silently vanish).
_background_tasks: set[asyncio.Task] = set()


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _semaphore


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply (handles ```json fences and prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start_positions = [p for p in (text.find("{"), text.find("[")) if p != -1]
        if not start_positions:
            raise
        start = min(start_positions)
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text[start:])
        return obj


class GeminiProvider:
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self) -> None:
        self.settings = get_settings()

    def model_for_tier(self, tier: str) -> str:
        s = self.settings
        return s.llm_model_strong if tier == TIER_STRONG else s.llm_model_fast

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        contents: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "user":
                content = m["content"]
                # Multimodal: content may already be a list of Gemini-style
                # parts ({"text"}, {"inlineData"}, {"fileData"}).
                parts = content if isinstance(content, list) else [{"text": content}]
                contents.append({"role": "user", "parts": parts})
            elif role == "assistant":
                parts: list[dict] = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for tc in m.get("tool_calls", []):
                    parts.append({"functionCall": {"name": tc.name, "args": tc.args}})
                contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            elif role == "tool_result":
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": m["name"],
                                    "response": {"result": m["result"]},
                                }
                            }
                        ],
                    }
                )
        return contents

    async def generate(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tools: list[dict] | None,
        json_schema: dict | None,
        temperature: float,
        max_tokens: int,
        thinking_budget: int | None = None,
    ) -> LlmResponse:
        body: dict[str, Any] = {
            "contents": self._convert_messages(messages),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if thinking_budget is not None:
            # Gemini 2.5 reasoning comes out of maxOutputTokens; an uncapped
            # think can starve the visible reply and truncate JSON mid-string.
            body["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": thinking_budget
            }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_schema is not None:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseSchema"] = json_schema
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                        }
                        for t in tools
                    ]
                }
            ]

        url = f"{self.BASE}/models/{model}:generateContent"
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                url,
                params={"key": self.settings.gemini_api_key},
                json=body,
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            # status_code 503 marks this as transient -> retried with backoff
            raise ExternalServiceError(
                f"Gemini unavailable ({resp.status_code}): {resp.text[:1500]}",
                status_code=503,
            )
        if resp.status_code >= 400:
            raise ExternalServiceError(
                f"Gemini rejected request ({resp.status_code}): {resp.text[:500]}",
                status_code=502,
            )
        data = resp.json()
        usage = data.get("usageMetadata", {})
        # Thinking models (Gemini 2.5) bill reasoning tokens as output —
        # count them, or budgets under-report real spend.
        visible = usage.get("candidatesTokenCount", 0) or 0
        thinking = usage.get("thoughtsTokenCount", 0) or 0
        out = LlmResponse(
            model=model,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=(visible + thinking) or usage.get("totalTokenCount", 0),
        )
        candidates = data.get("candidates") or []
        if candidates:
            for part in candidates[0].get("content", {}).get("parts", []):
                if "text" in part:
                    out.text += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    out.tool_calls.append(
                        ToolCall(name=fc.get("name", ""), args=fc.get("args") or {})
                    )
        return out


class ClaudeProvider:
    name = "claude"
    BASE = "https://api.anthropic.com/v1"

    def __init__(self) -> None:
        self.settings = get_settings()

    def model_for_tier(self, tier: str) -> str:
        s = self.settings
        return s.claude_model_strong if tier == TIER_STRONG else s.claude_model_fast

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        converted: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "user":
                content = m["content"]
                if isinstance(content, list):
                    blocks = []
                    for part in content:
                        if "text" in part:
                            blocks.append({"type": "text", "text": part["text"]})
                        elif "inlineData" in part:
                            mime = part["inlineData"].get("mimeType", "")
                            if not mime.startswith("image/"):
                                raise ExternalServiceError(
                                    "Claude provider supports image parts only; "
                                    "configure a dedicated STT provider for audio."
                                )
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": part["inlineData"]["data"],
                                    },
                                }
                            )
                    converted.append({"role": "user", "content": blocks})
                else:
                    converted.append({"role": "user", "content": content})
            elif role == "assistant":
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.call_id or f"call_{tc.name}",
                            "name": tc.name,
                            "input": tc.args,
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
            elif role == "tool_result":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("call_id") or f"call_{m['name']}",
                                "content": json.dumps(m["result"], default=str),
                            }
                        ],
                    }
                )
        return converted

    async def generate(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tools: list[dict] | None,
        json_schema: dict | None,
        temperature: float,
        max_tokens: int,
        thinking_budget: int | None = None,  # accepted for parity; Claude
        # models here run without extended thinking
    ) -> LlmResponse:
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": self._convert_messages(messages),
        }
        sys_prompt = system or ""
        if json_schema is not None:
            sys_prompt += (
                "\n\nRespond ONLY with valid JSON matching this schema:\n"
                + json.dumps(json_schema)
            )
        if sys_prompt:
            body["system"] = sys_prompt
        if tools:
            body["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{self.BASE}/messages",
                json=body,
                headers={
                    "x-api-key": self.settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ExternalServiceError(
                f"Claude unavailable ({resp.status_code}): {resp.text[:300]}",
                status_code=503,
            )
        if resp.status_code >= 400:
            raise ExternalServiceError(
                f"Claude rejected request ({resp.status_code}): {resp.text[:500]}",
                status_code=502,
            )
        data = resp.json()
        usage = data.get("usage", {})
        out = LlmResponse(
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
        for block in data.get("content", []):
            if block.get("type") == "text":
                out.text += block.get("text", "")
            elif block.get("type") == "tool_use":
                out.tool_calls.append(
                    ToolCall(
                        name=block.get("name", ""),
                        args=block.get("input") or {},
                        call_id=block.get("id", ""),
                    )
                )
        return out


class OpenRouterProvider:
    """OpenAI-compatible chat completions via OpenRouter — one key, hundreds
    of models, many free (":free" suffix). https://openrouter.ai/docs/quickstart

    Text, tools and image parts are supported. Audio STT and embeddings stay
    on Gemini (they are separate APIs, keyed by GEMINI_API_KEY regardless of
    the chat provider)."""

    name = "openrouter"
    BASE = "https://openrouter.ai/api/v1"

    def __init__(self) -> None:
        self.settings = get_settings()

    def model_for_tier(self, tier: str) -> str:
        s = self.settings
        return (
            s.openrouter_model_strong if tier == TIER_STRONG else s.openrouter_model_fast
        )

    def _convert_messages(self, messages: list[Message], system: str | None) -> list[dict]:
        converted: list[dict] = []
        if system:
            converted.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role")
            if role == "user":
                content = m["content"]
                if isinstance(content, list):
                    blocks: list[dict] = []
                    for part in content:
                        if "text" in part:
                            blocks.append({"type": "text", "text": part["text"]})
                        elif "inlineData" in part:
                            mime = part["inlineData"].get("mimeType", "")
                            if not mime.startswith("image/"):
                                raise ExternalServiceError(
                                    "OpenRouter provider supports image parts only; "
                                    "audio transcription stays on the Gemini STT path."
                                )
                            blocks.append(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,"
                                        + part["inlineData"]["data"]
                                    },
                                }
                            )
                    converted.append({"role": "user", "content": blocks})
                else:
                    converted.append({"role": "user", "content": content})
            elif role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {
                            "id": tc.call_id or f"call_{tc.name}",
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for tc in m["tool_calls"]
                    ]
                converted.append(msg)
            elif role == "tool_result":
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.get("call_id") or f"call_{m['name']}",
                        "content": json.dumps(m.get("result")),
                    }
                )
        return converted

    async def generate(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tools: list[dict] | None,
        json_schema: dict | None,
        temperature: float,
        max_tokens: int,
        thinking_budget: int | None = None,  # accepted for parity; reasoning
        # control varies per routed model, so we rely on max_tokens
    ) -> LlmResponse:
        # Structured-output support varies wildly across OpenRouter's free
        # models — the schema rides in the system prompt (the planning layer
        # re-validates and repairs), exactly like the Claude provider.
        sys_prompt = system or ""
        if json_schema is not None:
            sys_prompt += (
                "\n\nRespond ONLY with valid JSON matching this schema:\n"
                + json.dumps(json_schema)
            )
        body: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages, sys_prompt or None),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{self.BASE}/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    # Attribution headers OpenRouter asks apps to send.
                    "HTTP-Referer": "https://github.com/yuvipep/sales-platform",
                    "X-Title": self.settings.app_name,
                },
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            # Free models are often "temporarily rate-limited upstream" —
            # transient; the model layer retries and falls to the other tier.
            raise ExternalServiceError(
                f"OpenRouter unavailable ({resp.status_code}): {resp.text[:1500]}",
                status_code=503,
            )
        if resp.status_code >= 400:
            raise ExternalServiceError(
                f"OpenRouter rejected request ({resp.status_code}): {resp.text[:500]}",
                status_code=502,
            )
        data = resp.json()
        if data.get("error"):
            # Some routed providers tunnel errors inside a 200 envelope.
            code = str(data["error"].get("code", ""))
            raise ExternalServiceError(
                f"OpenRouter unavailable ({code}): {json.dumps(data['error'])[:1500]}",
                status_code=503 if code in ("429", "502", "503") else 502,
            )
        usage = data.get("usage", {})
        out = LlmResponse(
            model=model,
            input_tokens=usage.get("prompt_tokens", 0) or 0,
            output_tokens=usage.get("completion_tokens", 0) or 0,
        )
        message = (data.get("choices") or [{}])[0].get("message") or {}
        out.text = message.get("content") or ""
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            out.tool_calls.append(
                ToolCall(name=fn.get("name", ""), args=args, call_id=tc.get("id", ""))
            )
        return out


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model.endswith(":free"):
        return 0.0
    inp, outp = MODEL_COSTS.get(model, (0.5, 1.5))
    return round(input_tokens / 1e6 * inp + output_tokens / 1e6 * outp, 6)


class ModelLayer:
    """Public entry point used by all agents and services."""

    def __init__(self) -> None:
        self.settings = get_settings()
        providers = {
            "claude": ClaudeProvider,
            "openrouter": OpenRouterProvider,
            "gemini": GeminiProvider,
        }
        self._provider = providers.get(self.settings.llm_provider, GeminiProvider)()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def _check_budget(self, org_id: str | None) -> None:
        """Per-org monthly budget guard (doc §11.5)."""
        if org_id is None:
            return
        from app.database import SessionLocal
        from app.models.audit import LlmUsage
        from app.models.organisation import OrgSettings

        async with SessionLocal() as db:
            settings_row = (
                await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
            ).scalar_one_or_none()
            budget = (
                settings_row.llm_monthly_budget_usd
                if settings_row
                else self.settings.llm_default_org_monthly_budget_usd
            )
            month_start = time.strftime("%Y-%m-01")
            spent = (
                await db.execute(
                    select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0)).where(
                        LlmUsage.org_id == org_id,
                        LlmUsage.at >= month_start,
                    )
                )
            ).scalar_one()
            if spent >= budget:
                raise BudgetExceededError(
                    f"This organisation's monthly AI budget (${budget:.2f}) is used up. "
                    "An Org Admin can raise it in settings."
                )

    async def _record_usage(
        self,
        *,
        org_id: str | None,
        user_id: str | None,
        model: str,
        purpose: str,
        response: LlmResponse | None,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        from app.database import SessionLocal
        from app.models.audit import LlmUsage

        row = LlmUsage(
            org_id=org_id,
            user_id=user_id,
            provider=self._provider.name,
            model=model,
            purpose=purpose,
            input_tokens=response.input_tokens if response else 0,
            output_tokens=response.output_tokens if response else 0,
            cost_usd=_cost_usd(
                model,
                response.input_tokens if response else 0,
                response.output_tokens if response else 0,
            ),
            duration_ms=duration_ms,
            error=error,
        )

        async def _write() -> None:
            # Usage tracking must never break or stall a request. Model calls
            # usually run INSIDE a request transaction; on SQLite that
            # transaction holds the single write lock, so this insert must
            # happen after it commits — hence a background task with retries.
            for attempt in range(5):
                try:
                    async with SessionLocal() as db:
                        db.add(row)
                        await db.commit()
                        return
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(0.3 * (attempt + 1))
            logger.warning("LLM usage row dropped after retries (purpose=%s)", purpose)

        task = asyncio.create_task(_write())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def generate(
        self,
        *,
        purpose: str,
        messages: list[Message],
        system: str | None = None,
        tier: str = TIER_FAST,
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
        temperature: float = 0.3,
        # Generous by default: on thinking models (Gemini 2.5) reasoning
        # tokens come out of this budget before any visible text appears —
        # a small cap silently truncates JSON replies.
        max_tokens: int = 8192,
        thinking_budget: int | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> LlmResponse:
        await self._check_budget(org_id)
        model = self._provider.model_for_tier(tier)
        # Fallback for free-tier operation: if this model's DAILY quota is
        # exhausted, switch to the other tier's model instead of failing.
        fallback = self._provider.model_for_tier(
            TIER_STRONG if tier == TIER_FAST else TIER_FAST
        )
        max_retries = self.settings.llm_max_retries
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            started = time.monotonic()
            try:
                async with _get_semaphore():
                    response = await self._provider.generate(
                        model=model,
                        system=system,
                        messages=messages,
                        tools=tools,
                        json_schema=json_schema,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        thinking_budget=thinking_budget,
                    )
                await self._record_usage(
                    org_id=org_id,
                    user_id=user_id,
                    model=model,
                    purpose=purpose,
                    response=response,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                return response
            except (ExternalServiceError, httpx.HTTPError) as exc:
                last_error = exc
                if isinstance(exc, ExternalServiceError) and exc.status_code != 502:
                    # Transient (429/5xx). Quota exhaustion on one model won't
                    # clear quickly — switch to the other tier's model, which
                    # has its own separate quota bucket.
                    if "429" in str(exc)[:60] and model != fallback:
                        logger.warning(
                            "Model %s rate/quota limited; falling back to %s",
                            model, fallback,
                        )
                        model = fallback
                        continue
                elif isinstance(exc, ExternalServiceError):
                    # 4xx rejection — retrying won't help
                    await self._record_usage(
                        org_id=org_id, user_id=user_id, model=model, purpose=purpose,
                        response=None,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error=str(exc)[:500],
                    )
                    raise
                if attempt < max_retries:
                    delay = min(2**attempt + random.uniform(0, 1), 30)
                    logger.warning(
                        "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, max_retries + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)

        await self._record_usage(
            org_id=org_id, user_id=user_id, model=model, purpose=purpose,
            response=None, duration_ms=0, error=str(last_error)[:500],
        )
        raise ExternalServiceError(f"Model call failed after retries: {last_error}")

    async def generate_json(self, **kwargs: Any) -> Any:
        """Generate and parse a JSON reply (uses native structured output)."""
        response = await self.generate(**kwargs)
        return extract_json(response.text)


_model_layer: ModelLayer | None = None


def get_model_layer() -> ModelLayer:
    global _model_layer
    if _model_layer is None:
        _model_layer = ModelLayer()
    return _model_layer


def reset_model_layer() -> None:
    """Test hook / provider switch without restart."""
    global _model_layer
    _model_layer = None
