"""Model gateway: one model-agnostic entry point for every language-model call.

SEO Engine does not depend on any particular model. Every analysis, decision,
gate and action is deterministic code; a model is only ever asked to write
prose inside constraints the deterministic path already decided. So:

* **No model is required.** The default ``deterministic`` provider refuses to
  improvise and raises :class:`DeterministicFallbackRequired`; the caller runs
  its own deterministic path and says so (``synthesis_mode=deterministic``).
* **Any model can be connected.** A provider speaks a *protocol*, not a model:
  ``openai_compatible`` covers any Chat Completions endpoint, hosted or local
  (keyless servers included); ``anthropic`` covers any model served through
  the Anthropic Messages API; anything else can be added with
  :func:`register_provider`. The operator names the model; there is no default.
* **A model that fails never stops the platform.** Transient failures are
  retried; anything else raises :class:`ModelProviderError`, which callers
  treat exactly like "no model": they fall back to the deterministic path and
  record why.
* **No model-specific assumptions.** Sampling parameters are sent only when
  the operator sets them; protocol variants (an output-limit parameter a model
  will not accept) are adapted to from the provider's own error; cost is
  computed only from operator-supplied prices and is otherwise *unknown*.
* **No hidden reasoning leaks.** Reasoning blocks some models emit inline
  (``<think>…</think>`` and similar) are removed from every completion before
  any caller sees it (Rule 8).

Every call — successful or not — is appended to the gateway's usage log; the
Agent Runtime gives each run its own gateway and persists that log against the
run, so which model wrote what, and what it cost, is always attributable.
"""

from __future__ import annotations

import asyncio
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from seo_engine.shared.config import Settings, get_settings
from seo_engine.shared.errors import SEOEngineError


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class DeterministicFallbackRequired(SEOEngineError):
    """Raised by the offline provider: the caller must use its own logic."""

    code = "DETERMINISTIC_FALLBACK_REQUIRED"
    http_status = 503


class ModelProviderError(SEOEngineError):
    """A configured model could not produce a usable completion.

    ``retryable`` marks failures worth another attempt (timeouts, rate limits,
    server errors). Callers that can work without a model treat any of these as
    a reason to fall back, and record the reason.
    """

    code = "MODEL_PROVIDER_ERROR"
    http_status = 502

    def __init__(
        self, message: str, details: dict[str, Any] | None = None, *, retryable: bool = False
    ) -> None:
        super().__init__(message, details)
        self.retryable = retryable


class ModelUnavailable(ModelProviderError):
    """The configured provider cannot be used as configured."""

    code = "MODEL_UNAVAILABLE"
    http_status = 503


#: HTTP statuses a provider may return for a request that can succeed later.
RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


# --------------------------------------------------------------------------
# Messages, responses and usage
# --------------------------------------------------------------------------
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
    #: ``None`` when the provider did not report it. Never guessed.
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    #: ``None`` when no price is configured for the model. Never zero by default.
    estimated_cost_usd: float | None
    latency_ms: int
    succeeded: bool = True
    error: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    stop_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "estimated_cost_usd": (
                round(self.estimated_cost_usd, 6) if self.estimated_cost_usd is not None else None
            ),
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

    @property
    def truncated(self) -> bool:
        """Whether the model stopped because it hit the output limit."""
        return (self.stop_reason or "").lower() in {"max_tokens", "length", "max_output_tokens"}


def estimate_cost(
    input_tokens: int | None, output_tokens: int | None, settings: Settings | None = None
) -> float | None:
    """Cost from the operator's configured prices, or ``None`` if it is unknown.

    The platform ships no price list: prices differ by model, vendor, contract
    and date, and a stale built-in table would put fabricated figures in the
    usage ledger.
    """
    settings = settings or get_settings()
    in_price, out_price = settings.llm_input_price_per_mtok, settings.llm_output_price_per_mtok
    if in_price is None or out_price is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def approximate_tokens(text: str) -> int:
    """Rough token estimate, for sizing prompts only — never recorded as usage."""
    return max(1, len(text) // 4)


_REASONING_BLOCK = re.compile(
    r"<(think|thinking|reasoning|reflection)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_UNCLOSED_REASONING = re.compile(
    r"^\s*<(think|thinking|reasoning|reflection)\b[^>]*>", re.IGNORECASE
)


def strip_reasoning(text: str) -> str:
    """Remove inline reasoning blocks some models emit before their answer.

    Deliberation is never exposed (Rule 8). An opening reasoning tag that is
    never closed means the whole completion is deliberation, so nothing usable
    remains.
    """
    cleaned = _REASONING_BLOCK.sub("", text or "")
    if _UNCLOSED_REASONING.match(cleaned):
        return ""
    return cleaned.strip()


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None = None,
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
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        raise DeterministicFallbackRequired(
            "No language model provider is configured. The caller must produce its "
            "output deterministically from observed inputs, and label it "
            "synthesis_mode=deterministic.",
            {"configured_provider": "deterministic"},
        )


def _system_and_turns(messages: list[LLMMessage]) -> tuple[str, list[LLMMessage]]:
    """Channels are preserved: system and developer policy go in the system
    position and are never concatenated with untrusted material, which stays in
    its own (already fenced) user turn."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    return system, [m for m in messages if m.role != "system"]


class AnthropicProvider(LLMProvider):
    """Any model served through the Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        http_client: Any = None,
        timeout_seconds: float | None = None,
    ) -> None:
        # ``http_client`` is whatever client the installed SDK accepts; it
        # exists so tests can supply a fake transport.
        self.api_key = api_key
        self.base_url = base_url
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds
        self._send_temperature = True

    def _status_error(self, exc: Any, model: str) -> ModelProviderError:
        return ModelProviderError(
            f"the model provider returned HTTP {exc.status_code}",
            {
                "provider": self.name,
                "model": model,
                "status": exc.status_code,
                "body": str(exc.body)[:500],
            },
            retryable=exc.status_code in RETRYABLE_STATUSES,
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        import anthropic
        from anthropic.types import AssistantMessageParam, MessageParam, UserMessageParam

        # The gateway owns retries, uniformly for every provider.
        client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=self.http_client,
            max_retries=0,
            timeout=self.timeout_seconds or anthropic.NOT_GIVEN,
        )
        system, turns = _system_and_turns(messages)
        conversation: list[MessageParam] = [
            AssistantMessageParam(role="assistant", content=m.content)
            if m.role == "assistant"
            else UserMessageParam(role="user", content=m.content)
            for m in turns
        ]

        started = time.perf_counter()
        while True:
            # A temperature is sent only when the operator configured one, and
            # dropped if the model says it does not accept the parameter.
            sampling = (
                {"temperature": temperature}
                if temperature is not None and self._send_temperature
                else None
            )
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system or anthropic.omit,
                    messages=conversation,
                    extra_body=sampling,
                )
                break
            except anthropic.APIStatusError as exc:
                if sampling and exc.status_code == 400 and "temperature" in str(exc.body).lower():
                    self._send_temperature = False
                    continue
                raise self._status_error(exc, model) from exc
            except anthropic.APIConnectionError as exc:  # includes timeouts
                raise ModelProviderError(
                    f"the model provider could not be reached: {exc}",
                    {"provider": self.name, "model": model},
                    retryable=True,
                ) from exc

        latency = int((time.perf_counter() - started) * 1000)
        text = "".join(
            getattr(block, "text", "") for block in response.content if block.type == "text"
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        return LLMResponse(
            text=text,
            usage=LLMUsageRecord(
                provider=self.name,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=getattr(usage, "cache_read_input_tokens", None),
                estimated_cost_usd=estimate_cost(input_tokens, output_tokens),
                latency_ms=latency,
                stop_reason=response.stop_reason,
            ),
            stop_reason=response.stop_reason,
        )


class OpenAICompatibleProvider(LLMProvider):
    """Any endpoint speaking the Chat Completions protocol.

    Hosted APIs and local servers alike: the API key is optional (a local
    server usually needs none) and the endpoint is whatever the operator
    configured. Protocol variants are adapted to from the server's own answer:
    if it rejects ``max_tokens`` in favour of ``max_completion_tokens``, or
    rejects a sampling temperature, the request is repeated without the
    offending parameter, and the provider remembers it.
    """

    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = client
        self.timeout_seconds = timeout_seconds
        self._limit_param = "max_tokens"
        self._send_temperature = True

    def _body(
        self, messages: list[LLMMessage], *, model: str, max_tokens: int, temperature: float | None
    ) -> dict[str, Any]:
        system, turns = _system_and_turns(messages)
        conversation = [{"role": "system", "content": system}] if system else []
        conversation += [{"role": m.role, "content": m.content} for m in turns]
        body: dict[str, Any] = {"model": model, "messages": conversation}
        body[self._limit_param] = max_tokens
        if temperature is not None and self._send_temperature:
            body["temperature"] = temperature
        return body

    def _adapt(self, response: httpx.Response, body: dict[str, Any]) -> bool:
        """Adjust to a parameter the server says it does not accept."""
        if response.status_code != 400:
            return False
        text = response.text.lower()
        if self._limit_param == "max_tokens" and "max_completion_tokens" in text:
            self._limit_param = "max_completion_tokens"
            return True
        if "temperature" in body and "temperature" in text:
            self._send_temperature = False
            return True
        return False

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds or get_settings().llm_timeout_seconds
        )
        started = time.perf_counter()
        try:
            for _ in range(3):  # at most two protocol adaptations
                body = self._body(
                    messages, model=model, max_tokens=max_tokens, temperature=temperature
                )
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", headers=headers, json=body
                    )
                except httpx.HTTPError as exc:
                    raise ModelProviderError(
                        f"the model provider could not be reached: {exc}",
                        {"provider": self.name, "model": model},
                        retryable=True,
                    ) from exc
                if not self._adapt(response, body):
                    break
        finally:
            if self._client is None:
                await client.aclose()
        latency = int((time.perf_counter() - started) * 1000)

        if response.status_code >= 400:
            raise ModelProviderError(
                f"the model provider returned HTTP {response.status_code}",
                {
                    "provider": self.name,
                    "model": model,
                    "status": response.status_code,
                    "body": response.text[:500],
                },
                retryable=response.status_code in RETRYABLE_STATUSES,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                "the model provider returned a response that is not JSON",
                {"provider": self.name, "model": model, "body": response.text[:500]},
            ) from exc

        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, list):  # some servers return content parts
            content = "".join(
                str(part.get("text") or "") for part in content if isinstance(part, dict)
            )
        usage_data = data.get("usage") or {}
        input_tokens = usage_data.get("prompt_tokens")
        output_tokens = usage_data.get("completion_tokens")
        stop_reason = choice.get("finish_reason")
        return LLMResponse(
            text=str(content or ""),
            usage=LLMUsageRecord(
                provider=self.name,
                model=str(data.get("model") or model),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=(usage_data.get("prompt_tokens_details") or {}).get("cached_tokens"),
                estimated_cost_usd=estimate_cost(input_tokens, output_tokens),
                latency_ms=latency,
                stop_reason=stop_reason,
            ),
            stop_reason=stop_reason,
        )


# --------------------------------------------------------------------------
# The provider registry
# --------------------------------------------------------------------------
ProviderFactory = Callable[[Settings], LLMProvider]
_PROVIDERS: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Make a provider selectable as ``LLM_PROVIDER=<name>``.

    The factory receives the settings and returns a provider, or raises
    :class:`ModelUnavailable` explaining what configuration is missing.
    """
    _PROVIDERS[name.strip().lower()] = factory


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def _deterministic(_: Settings) -> LLMProvider:
    return DeterministicProvider()


def _anthropic(settings: Settings) -> LLMProvider:
    if not settings.llm_api_key:
        raise ModelUnavailable(
            "LLM_PROVIDER=anthropic needs LLM_API_KEY", {"provider": "anthropic"}
        )
    return AnthropicProvider(
        settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _openai_compatible(settings: Settings) -> LLMProvider:
    if not settings.llm_base_url:
        raise ModelUnavailable(
            "LLM_PROVIDER=openai_compatible needs LLM_BASE_URL: the endpoint of the Chat "
            "Completions API you connected (a hosted API or a local server)",
            {"provider": "openai_compatible"},
        )
    return OpenAICompatibleProvider(
        settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
    )


register_provider("deterministic", _deterministic)
register_provider("anthropic", _anthropic)
register_provider("openai_compatible", _openai_compatible)


def _build_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    factory = _PROVIDERS.get(settings.llm_provider)
    if factory is None:
        raise ModelUnavailable(
            f"no model provider is registered as '{settings.llm_provider}'",
            {"provider": settings.llm_provider, "registered": available_providers()},
        )
    return factory(settings)


# --------------------------------------------------------------------------
# The gateway
# --------------------------------------------------------------------------
Sleep = Callable[[float], Awaitable[None]]


class ModelGateway:
    """The single entry point for model calls."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        model: str | None = None,
        max_retries: int | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self._model = model
        self._max_retries = max_retries
        self._sleep = sleep
        self.usage_log: list[LLMUsageRecord] = []

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = _build_provider()
        return self._provider

    @property
    def available(self) -> bool:
        try:
            return not isinstance(self.provider, DeterministicProvider)
        except ModelUnavailable:
            return False

    def status(self) -> dict[str, Any]:
        """What the gateway would use, for readiness reporting. Makes no call."""
        settings = get_settings()
        info: dict[str, Any] = {
            "provider": settings.llm_provider if self._provider is None else self._provider.name,
            "model": self._model or settings.llm_model,
        }
        try:
            provider = self.provider
        except ModelUnavailable as exc:
            # Configured but unusable: the platform runs without it, and says why.
            return {**info, "mode": "deterministic", "problem": exc.message}
        info["mode"] = "deterministic" if isinstance(provider, DeterministicProvider) else "model"
        return info

    def scoped(self) -> ModelGateway:
        """A gateway with its own usage log, sharing this one's provider.

        The Agent Runtime gives every run one, so each call is attributed to
        the run that made it.
        """
        try:
            provider: LLMProvider | None = self.provider
        except ModelUnavailable:
            provider = None  # resolved (and reported) on first use
        return ModelGateway(
            provider, model=self._model, max_retries=self._max_retries, sleep=self._sleep
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prompt_key: str | None = None,
        prompt_version: str | None = None,
    ) -> LLMResponse:
        settings = get_settings()
        provider = self.provider  # DeterministicFallbackRequired / ModelUnavailable propagate
        if isinstance(provider, DeterministicProvider):
            return await provider.complete(messages, model="", max_tokens=0)

        model_name = model or self._model or settings.llm_model
        if not model_name:
            raise ModelUnavailable("no model is named (set LLM_MODEL)", {"provider": provider.name})
        retries = settings.llm_max_retries if self._max_retries is None else self._max_retries
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                response = await provider.complete(
                    messages,
                    model=model_name,
                    max_tokens=max_tokens or settings.llm_max_output_tokens,
                    temperature=temperature
                    if temperature is not None
                    else settings.llm_temperature,
                )
            except ModelProviderError as exc:
                self._record_failure(provider, model_name, exc, started, prompt_key, prompt_version)
                if exc.retryable and attempt < retries:
                    await self._sleep(min(8.0, 0.5 * 2**attempt))
                    attempt += 1
                    continue
                raise
            break

        response.text = strip_reasoning(response.text)
        response.usage.prompt_key = prompt_key
        response.usage.prompt_version = prompt_version
        if not response.text:
            response.usage.succeeded = False
            response.usage.error = "the model returned no usable text"
            self.usage_log.append(response.usage)
            raise ModelProviderError(
                "the model returned no usable text",
                {
                    "provider": provider.name,
                    "model": model_name,
                    "stop_reason": response.stop_reason,
                },
            )
        self.usage_log.append(response.usage)
        return response

    def _record_failure(
        self,
        provider: LLMProvider,
        model: str,
        exc: ModelProviderError,
        started: float,
        prompt_key: str | None,
        prompt_version: str | None,
    ) -> None:
        self.usage_log.append(
            LLMUsageRecord(
                provider=provider.name,
                model=model,
                input_tokens=None,
                output_tokens=None,
                cached_tokens=None,
                estimated_cost_usd=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                succeeded=False,
                error=exc.message[:500],
                prompt_key=prompt_key,
                prompt_version=prompt_version,
            )
        )


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
    "RETRYABLE_STATUSES",
    "AnthropicProvider",
    "DeterministicFallbackRequired",
    "DeterministicProvider",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMUsageRecord",
    "ModelGateway",
    "ModelProviderError",
    "ModelUnavailable",
    "OpenAICompatibleProvider",
    "approximate_tokens",
    "available_providers",
    "estimate_cost",
    "get_gateway",
    "register_provider",
    "set_gateway",
    "strip_reasoning",
]
