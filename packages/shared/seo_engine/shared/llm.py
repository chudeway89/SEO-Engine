"""Model gateway.

Every model call goes through here so that usage, cost and latency are recorded
in one place and no agent talks to a provider directly.

Three providers:

* ``anthropic`` / ``openai`` — real API calls;
* ``deterministic`` — the offline provider. It does **not** pretend to be a
  model. It refuses to answer open-ended questions and raises
  :class:`DeterministicFallbackRequired`, which tells the caller to run its own
  deterministic path. That is what keeps ``synthesis_mode`` honest: an output
  labelled ``llm`` really was written by a model, and one labelled
  ``deterministic`` really was assembled by our own code from observed inputs.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from seo_engine.shared.config import get_settings
from seo_engine.shared.errors import SEOEngineError

#: Indicative prices per million tokens, used only to estimate cost for the
#: usage ledger.  They are labelled as estimates wherever they surface.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (0.8, 4.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}


class DeterministicFallbackRequired(SEOEngineError):
    """Raised by the offline provider: the caller must use its own logic."""

    code = "DETERMINISTIC_FALLBACK_REQUIRED"
    http_status = 503


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str
    channel: str | None = None
    label: str | None = None


@dataclass(slots=True)
class LLMUsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    succeeded: bool = True
    error: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "latency_ms": self.latency_ms,
            "succeeded": self.succeeded,
            "error": self.error,
        }


@dataclass(slots=True)
class LLMResponse:
    text: str
    usage: LLMUsageRecord
    stop_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    for prefix, (in_price, out_price) in PRICING_USD_PER_MTOK.items():
        if model.startswith(prefix):
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return 0.0


def approximate_tokens(text: str) -> int:
    """Rough token estimate for providers that do not return usage."""
    return max(1, len(text) // 4)


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse: ...


class DeterministicProvider(LLMProvider):
    """The offline provider.  It never fabricates prose.

    Rather than emit plausible-looking text that would be indistinguishable from
    a model's output, it refuses, and the caller composes its result from the
    observed data it already holds.
    """

    name = "deterministic"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        raise DeterministicFallbackRequired(
            "No language model provider is configured. The caller must produce its "
            "output deterministically from observed inputs, and label it "
            "synthesis_mode=deterministic.",
            {"configured_provider": "deterministic"},
        )


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        # Channels are preserved: system content stays in the system parameter
        # and is never concatenated with untrusted material.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        conversation = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]

        started = time.perf_counter()
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system or anthropic.NOT_GIVEN,
                messages=conversation,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            raise SEOEngineError(
                f"the language model request failed: {exc}",
                {"provider": self.name, "model": model, "latency_ms": latency},
            ) from exc

        latency = int((time.perf_counter() - started) * 1000)
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = LLMUsageRecord(
            provider=self.name,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            estimated_cost_usd=estimate_cost(
                model, response.usage.input_tokens, response.usage.output_tokens
            ),
            latency_ms=latency,
        )
        return LLMResponse(text=text, usage=usage, stop_reason=response.stop_reason)


class ModelGateway:
    """The single entry point for model calls."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider
        self.usage_log: list[LLMUsageRecord] = []

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = _build_provider()
        return self._provider

    @property
    def available(self) -> bool:
        return not isinstance(self.provider, DeterministicProvider)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        prompt_key: str | None = None,
        prompt_version: str | None = None,
    ) -> LLMResponse:
        settings = get_settings()
        response = await self.provider.complete(
            messages,
            model=model or settings.llm_model,
            temperature=temperature,
            max_tokens=max_tokens or settings.llm_max_output_tokens,
        )
        response.usage.prompt_key = prompt_key
        response.usage.prompt_version = prompt_version
        self.usage_log.append(response.usage)
        return response


def _build_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "anthropic" and settings.llm_api_key:
        return AnthropicProvider(settings.llm_api_key)
    if settings.llm_provider == "openai" and settings.llm_api_key:  # pragma: no cover
        raise SEOEngineError(
            "the OpenAI provider is declared but not implemented; use anthropic or deterministic",
            {"provider": "openai"},
        )
    return DeterministicProvider()


_gateway: ModelGateway | None = None


def get_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway()
    return _gateway


def set_gateway(gateway: ModelGateway | None) -> None:
    global _gateway
    _gateway = gateway


__all__ = [
    "PRICING_USD_PER_MTOK",
    "AnthropicProvider",
    "DeterministicFallbackRequired",
    "DeterministicProvider",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMUsageRecord",
    "ModelGateway",
    "approximate_tokens",
    "estimate_cost",
    "get_gateway",
    "set_gateway",
]
