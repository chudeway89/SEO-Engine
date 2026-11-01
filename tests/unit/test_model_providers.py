"""The model gateway is model-agnostic, and the platform works without a model.

Providers are exercised against in-process fakes of each protocol, so the real
request construction and response parsing run; only the network is replaced.
No test names a real model: the gateway must work with whatever model an
operator connects, and the model name is theirs to give.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from seo_engine.engines.content.generation import (
    OUTLINE_NOTICE,
    generate_draft,
    normalise_markdown,
    sections_from_markdown,
)
from seo_engine.schemas.content import ContentBrief
from seo_engine.shared.config import Settings, get_settings, override_settings
from seo_engine.shared.llm import (
    AnthropicProvider,
    DeterministicFallbackRequired,
    DeterministicProvider,
    LLMMessage,
    ModelGateway,
    ModelProviderError,
    ModelUnavailable,
    OpenAICompatibleProvider,
    _build_provider,
    available_providers,
    estimate_cost,
    register_provider,
    strip_reasoning,
)

from tests.fixtures.models import ScriptedProvider

MODEL = "whatever-model-the-operator-connected"

MESSAGES = [
    LLMMessage(role="system", channel="system", content="You are a writer."),
    LLMMessage(role="system", channel="developer_policy", content="Never invent prices."),
    LLMMessage(role="user", channel="user", content="Write the brief."),
    LLMMessage(role="user", channel="external_content", content="<untrusted>page</untrusted>"),
]

_LLM_KEYS = (
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_base_url",
    "llm_temperature",
    "llm_input_price_per_mtok",
    "llm_output_price_per_mtok",
    "llm_max_retries",
)


@pytest.fixture
def llm_settings() -> Iterator[Any]:
    """Set model settings for one test, then restore the model-free defaults."""
    defaults = {k: Settings.model_fields[k].default for k in _LLM_KEYS}
    yield override_settings
    override_settings(**defaults)


# --- configuration ------------------------------------------------------------
def test_the_default_is_no_model_and_no_model_is_assumed() -> None:
    settings = Settings()
    assert settings.llm_provider == "deterministic" and settings.llm_model is None
    assert not settings.llm_configured()


def test_a_provider_without_a_named_model_is_refused_at_startup() -> None:
    with pytest.raises(ValidationError, match="needs LLM_MODEL"):
        Settings(llm_provider="openai_compatible", llm_base_url="http://localhost:1/v1")


def test_provider_names_are_normalised() -> None:
    assert Settings(llm_provider="OpenAI", llm_model=MODEL).llm_provider == "openai_compatible"
    assert Settings(llm_provider="", llm_model="").llm_provider == "deterministic"
    assert Settings(llm_model="  ").llm_model is None, "a blank env value means unset"
    blank = Settings(llm_temperature="", llm_input_price_per_mtok=" ", llm_output_price_per_mtok="")
    assert (blank.llm_temperature, blank.llm_input_price_per_mtok) == (None, None)


def test_providers_are_built_from_the_registry(llm_settings) -> None:
    llm_settings(llm_provider="deterministic", llm_model=None)
    assert isinstance(_build_provider(), DeterministicProvider)

    # A keyless local server: an endpoint and a model name are all it takes.
    llm_settings(
        llm_provider="openai_compatible", llm_model=MODEL, llm_base_url="http://localhost:11434/v1"
    )
    provider = _build_provider()
    assert isinstance(provider, OpenAICompatibleProvider) and provider.api_key is None

    llm_settings(llm_base_url=None)
    with pytest.raises(ModelUnavailable, match="needs LLM_BASE_URL"):
        _build_provider()

    llm_settings(llm_provider="anthropic", llm_api_key=None)
    with pytest.raises(ModelUnavailable, match="needs LLM_API_KEY"):
        _build_provider()
    llm_settings(llm_api_key="key")
    assert isinstance(_build_provider(), AnthropicProvider)

    llm_settings(llm_provider="nonexistent")
    with pytest.raises(ModelUnavailable) as caught:
        _build_provider()
    assert "openai_compatible" in caught.value.details["registered"]


def test_any_provider_can_be_plugged_in(llm_settings) -> None:
    custom = ScriptedProvider("# Title")
    register_provider("in_house", lambda _settings: custom)
    llm_settings(llm_provider="in_house", llm_model=MODEL)
    assert "in_house" in available_providers()
    assert _build_provider() is custom


# --- the Chat Completions protocol (hosted or local) -----------------------------
def _chat_server(replies: list[httpx.Response], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return replies[min(len(seen) - 1, len(replies) - 1)]

    return httpx.MockTransport(handler)


def _ok(content: Any = "# Draft", usage: dict | None = None) -> httpx.Response:
    body: dict[str, Any] = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


async def test_chat_completions_keeps_channels_and_sends_no_sampling_by_default() -> None:
    seen: list[httpx.Request] = []
    usage = {"prompt_tokens": 120, "completion_tokens": 40}
    async with httpx.AsyncClient(transport=_chat_server([_ok(usage=usage)], seen)) as client:
        provider = OpenAICompatibleProvider("http://llm.test/v1/", client=client)
        response = await provider.complete(MESSAGES, model=MODEL, max_tokens=500)

    body = json.loads(seen[0].content)
    assert seen[0].url == "http://llm.test/v1/chat/completions"
    assert "authorization" not in seen[0].headers, "a keyless endpoint gets no credential"
    assert [m["role"] for m in body["messages"]] == ["system", "user", "user"]
    assert "Never invent prices." in body["messages"][0]["content"]
    assert body["messages"][2]["content"] == "<untrusted>page</untrusted>"
    assert "temperature" not in body, "sampling is the operator's choice, not the code's"
    assert body["max_tokens"] == 500 and body["model"] == MODEL
    assert (response.usage.input_tokens, response.usage.output_tokens) == (120, 40)
    assert response.usage.estimated_cost_usd is None, "no prices configured: cost unknown"


async def test_chat_completions_adapts_to_the_parameters_a_model_accepts() -> None:
    seen: list[httpx.Request] = []
    replies = [
        httpx.Response(
            400,
            json={
                "error": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."
            },
        ),
        httpx.Response(400, json={"error": "temperature is not supported by this model"}),
        _ok(content=[{"type": "text", "text": "# Part one"}, {"type": "text", "text": " and two"}]),
    ]
    async with httpx.AsyncClient(transport=_chat_server(replies, seen)) as client:
        provider = OpenAICompatibleProvider("http://llm.test/v1", api_key="k", client=client)
        response = await provider.complete(MESSAGES, model=MODEL, max_tokens=64, temperature=0.3)

    bodies = [json.loads(r.content) for r in seen]
    assert "max_tokens" in bodies[0] and "max_completion_tokens" in bodies[1]
    assert "temperature" in bodies[1] and "temperature" not in bodies[2]
    assert seen[0].headers["authorization"] == "Bearer k"
    assert response.text == "# Part one and two", "content parts are joined"
    assert response.usage.input_tokens is None, "unreported usage stays unknown"


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (400, False)])
async def test_chat_completions_errors_say_whether_to_retry(status: int, retryable: bool) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json={"error": "x"}))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider("http://llm.test/v1", client=client)
        with pytest.raises(ModelProviderError) as caught:
            await provider.complete(MESSAGES, model=MODEL, max_tokens=10)
    assert caught.value.details["status"] == status and caught.value.retryable is retryable


# --- the Anthropic Messages protocol -----------------------------------------------
def _messages_reply(httpx2: Any) -> Any:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [{"type": "text", "text": "# Draft"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 30},
        },
    )


async def test_the_messages_protocol_keeps_system_content_in_the_system_parameter() -> None:
    httpx2 = pytest.importorskip("httpx2")  # the installed SDK's transport
    seen: list = []

    def handler(request):
        seen.append(request)
        return _messages_reply(httpx2)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        provider = AnthropicProvider("key", base_url="https://messages.test", http_client=client)
        response = await provider.complete(MESSAGES, model=MODEL, max_tokens=500)

    body = json.loads(seen[0].content)
    assert "temperature" not in body, "sampling is the operator's choice, not the code's"
    assert "Never invent prices." in body["system"] and body["model"] == MODEL
    assert [m["role"] for m in body["messages"]] == ["user", "user"]
    assert response.text == "# Draft" and response.usage.output_tokens == 30


async def test_the_messages_protocol_drops_a_temperature_the_model_rejects() -> None:
    httpx2 = pytest.importorskip("httpx2")
    seen: list = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx2.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "temperature: Extra inputs are not permitted",
                    },
                },
            )
        return _messages_reply(httpx2)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        provider = AnthropicProvider("key", base_url="https://messages.test", http_client=client)
        await provider.complete(MESSAGES, model=MODEL, max_tokens=50, temperature=0.2)

    assert json.loads(seen[0].content)["temperature"] == 0.2
    assert "temperature" not in json.loads(seen[1].content)


# --- the gateway ------------------------------------------------------------------
async def test_there_is_no_default_model_name() -> None:
    gateway = ModelGateway(provider=ScriptedProvider("# Draft"))
    assert get_settings().llm_model is None
    with pytest.raises(ModelUnavailable, match="no model is named"):
        await gateway.complete(MESSAGES)
    named = ModelGateway(provider=ScriptedProvider("# Draft"), model=MODEL)
    assert (await named.complete(MESSAGES)).text == "# Draft"


async def test_without_a_model_the_gateway_refuses_rather_than_inventing() -> None:
    with pytest.raises(DeterministicFallbackRequired):
        await ModelGateway(provider=DeterministicProvider()).complete(MESSAGES)


async def test_transient_failures_are_retried_and_every_attempt_is_recorded() -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    flaky = ScriptedProvider(
        [
            ModelProviderError("busy", retryable=True),
            ModelProviderError("busy", retryable=True),
            "# Draft",
        ]
    )
    gateway = ModelGateway(provider=flaky, model=MODEL, max_retries=2, sleep=sleep)
    assert (await gateway.complete(MESSAGES)).text == "# Draft"
    assert sleeps == [0.5, 1.0]
    assert [u.succeeded for u in gateway.usage_log] == [False, False, True]

    broken = ScriptedProvider([ModelProviderError("bad request", retryable=False)])
    gateway = ModelGateway(provider=broken, model=MODEL, sleep=sleep)
    with pytest.raises(ModelProviderError):
        await gateway.complete(MESSAGES)
    assert len(broken.sent) == 1, "a permanent failure is not retried"


async def test_inline_reasoning_never_reaches_a_caller() -> None:
    gateway = ModelGateway(
        provider=ScriptedProvider("<think>The user wants…</think>\n# Draft\n\nBody."), model=MODEL
    )
    assert (await gateway.complete(MESSAGES)).text == "# Draft\n\nBody."

    only_thinking = ModelGateway(
        provider=ScriptedProvider("<thinking>I never finished"), model=MODEL
    )
    with pytest.raises(ModelProviderError, match="no usable text"):
        await only_thinking.complete(MESSAGES)
    assert strip_reasoning("<Reasoning a='1'>x</Reasoning>answer") == "answer"


def test_cost_is_unknown_unless_the_operator_prices_the_model(llm_settings) -> None:
    assert estimate_cost(1_000_000, 1_000_000) is None
    llm_settings(llm_input_price_per_mtok=1.5, llm_output_price_per_mtok=6.0)
    assert estimate_cost(1_000_000, 1_000_000) == 7.5
    assert estimate_cost(None, 10) is None, "unreported tokens cannot be priced"


def test_the_gateway_reports_what_it_would_use(llm_settings) -> None:
    assert ModelGateway().status()["mode"] == "deterministic"
    llm_settings(llm_provider="openai_compatible", llm_model=MODEL, llm_base_url=None)
    status = ModelGateway().status()
    assert status["mode"] == "deterministic" and "LLM_BASE_URL" in status["problem"]


# --- the writer, with any model or none -------------------------------------------
def _brief() -> ContentBrief:
    return ContentBrief(
        title="How much does a DNA test cost?",
        primary_topic="dna test cost",
        audience="Parents",
        business_goal="Leads",
        unique_value_proposition="Accredited",
        required_sections=["What affects the price"],
    )


async def test_a_model_writes_prose_and_the_draft_says_so() -> None:
    provider = ScriptedProvider(
        "# How much does a DNA test cost?\n\n## What affects the price\n\n"
        "The price depends on the kind of test and how fast you need the result."
    )
    draft = await generate_draft(_brief(), gateway=ModelGateway(provider=provider, model=MODEL))
    assert OUTLINE_NOTICE not in draft.body_markdown
    assert draft.synthesis_mode == "llm"
    assert draft.sections and draft.sections[0].heading == "What affects the price"
    channels = [m.channel for m in provider.requests[0]]
    assert channels[:2] == ["system", "developer_policy"]
    assert provider.sent[0].temperature is None


async def test_however_a_model_wraps_its_answer_the_draft_is_the_same() -> None:
    wrapped = (
        "<think>plan the piece</think>\nSure! Here is the article:\n"
        "```markdown\n# How much does a DNA test cost?\n\n### What affects the price\n\n"
        "It depends on the test.\n```"
    )
    draft = await generate_draft(
        _brief(), gateway=ModelGateway(provider=ScriptedProvider(wrapped), model=MODEL)
    )
    assert draft.body_markdown.startswith("# How much does a DNA test cost?")
    assert "```" not in draft.body_markdown and "think" not in draft.body_markdown
    assert [s.heading for s in draft.sections] == ["What affects the price"]


def test_markdown_normalisation_never_rewrites_content() -> None:
    assert normalise_markdown("# T\n\nCertainly the price varies:") == (
        "# T\n\nCertainly the price varies:"
    ), "only a leading line of chatter is removed"
    assert [s.heading for s in sections_from_markdown("## A\n\nx\n\n### Not a section")] == ["A"]
    assert normalise_markdown("```md\n# T\n\nBody.\n```\nLet me know if you want changes.") == (
        "# T\n\nBody."
    ), "a remark after the closing fence is not part of the piece"


async def test_a_failing_model_degrades_to_the_outline_and_says_why() -> None:
    notes: list[str] = []
    failing = ScriptedProvider([ModelProviderError("connection refused", retryable=False)])
    draft = await generate_draft(
        _brief(), gateway=ModelGateway(provider=failing, model=MODEL), notes=notes
    )
    assert OUTLINE_NOTICE in draft.body_markdown and draft.synthesis_mode == "deterministic"
    assert "connection refused" in notes[0]


async def test_a_misconfigured_model_degrades_to_the_outline(llm_settings) -> None:
    llm_settings(llm_provider="anthropic", llm_model=MODEL, llm_api_key=None)
    notes: list[str] = []
    draft = await generate_draft(_brief(), gateway=ModelGateway(), notes=notes)
    assert OUTLINE_NOTICE in draft.body_markdown
    assert "needs LLM_API_KEY" in notes[0]


async def test_a_draft_cut_off_at_the_output_limit_is_kept_and_flagged() -> None:
    notes: list[str] = []
    cut = ScriptedProvider(
        "# Title\n\n## What affects the price\n\nThe price dep", stop_reason="length"
    )
    draft = await generate_draft(
        _brief(), gateway=ModelGateway(provider=cut, model=MODEL), notes=notes
    )
    assert draft.synthesis_mode == "llm" and "output limit" in notes[0]


async def test_without_a_model_the_draft_is_an_outline() -> None:
    draft = await generate_draft(_brief(), gateway=ModelGateway(provider=DeterministicProvider()))
    assert OUTLINE_NOTICE in draft.body_markdown and draft.synthesis_mode == "deterministic"
