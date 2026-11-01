"""Model providers against in-process fake APIs.

The real request construction and response parsing run; only the network is
replaced. Channel separation is asserted: system and developer policy travel in
the system position, and untrusted material stays in its own user message.
"""

from __future__ import annotations

import json

import httpx
import pytest
from seo_engine.engines.content.generation import OUTLINE_NOTICE, generate_draft
from seo_engine.schemas.content import ContentBrief
from seo_engine.shared.config import override_settings
from seo_engine.shared.errors import SEOEngineError
from seo_engine.shared.llm import (
    AnthropicProvider,
    DeterministicProvider,
    LLMMessage,
    ModelGateway,
    OpenAIProvider,
    _build_provider,
    estimate_cost,
)

from tests.fixtures.models import ScriptedProvider

MESSAGES = [
    LLMMessage(role="system", channel="system", content="You are a writer."),
    LLMMessage(role="system", channel="developer_policy", content="Never invent prices."),
    LLMMessage(role="user", channel="user", content="Write the brief."),
    LLMMessage(role="user", channel="external_content", content="<untrusted>page</untrusted>"),
]


async def test_the_openai_provider_sends_one_system_message_and_parses_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "# Draft"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIProvider("sk-test", base_url="https://llm.test/v1", client=client)
        response = await provider.complete(
            MESSAGES, model="gpt-4o", temperature=0.2, max_tokens=500
        )

    body = json.loads(seen[0].content)
    assert seen[0].url == "https://llm.test/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert [m["role"] for m in body["messages"]] == ["system", "user", "user"]
    assert "Never invent prices." in body["messages"][0]["content"]
    assert body["messages"][2]["content"] == "<untrusted>page</untrusted>", (
        "untrusted stays separate"
    )
    assert response.text == "# Draft" and response.stop_reason == "stop"
    assert (response.usage.input_tokens, response.usage.output_tokens) == (120, 40)
    assert response.usage.estimated_cost_usd > 0


async def test_an_openai_error_is_raised_not_swallowed() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(429, json={"error": "rate"}))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAIProvider("sk", client=client)
        with pytest.raises(SEOEngineError) as caught:
            await provider.complete(MESSAGES, model="gpt-4o", temperature=0, max_tokens=10)
    assert caught.value.details["status"] == 429


async def test_the_anthropic_provider_keeps_system_content_in_the_system_parameter() -> None:
    seen: list = []

    def handler(request):
        import httpx2

        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": "# Draft"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 30},
            },
        )

    # The installed SDK uses the httpx2 fork for its transport.
    httpx2 = pytest.importorskip("httpx2")
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        provider = AnthropicProvider("key", base_url="https://anthropic.test", http_client=client)
        response = await provider.complete(
            MESSAGES, model="claude-opus-5-5", temperature=0.2, max_tokens=500
        )

    body = json.loads(seen[0].content)
    assert "temperature" not in body, "the Messages API rejects a sampling temperature"
    assert "Never invent prices." in body["system"]
    assert [m["role"] for m in body["messages"]] == ["user", "user"]
    assert response.text == "# Draft"
    assert response.usage.output_tokens == 30


def test_the_configured_provider_is_built_and_absent_keys_fall_back() -> None:
    try:
        override_settings(llm_provider="openai", llm_api_key="sk-x", llm_base_url=None)
        assert isinstance(_build_provider(), OpenAIProvider)
        override_settings(llm_provider="anthropic", llm_api_key="k")
        assert isinstance(_build_provider(), AnthropicProvider)
        override_settings(llm_provider="anthropic", llm_api_key=None)
        assert isinstance(_build_provider(), DeterministicProvider)
    finally:
        override_settings(llm_provider="deterministic", llm_api_key=None)


def test_cost_estimates_match_the_most_specific_model_name() -> None:
    # 1M input + 1M output tokens: the estimate is the sum of the two list prices.
    assert estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert estimate_cost("claude-opus-5", 1_000_000, 1_000_000) == 30.0
    assert estimate_cost("gpt-4o-mini", 1_000_000, 0) == 0.15
    assert estimate_cost("an-unknown-model", 1_000_000, 1_000_000) == 0.0


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
    draft = await generate_draft(_brief(), gateway=ModelGateway(provider=provider))
    assert OUTLINE_NOTICE not in draft.body_markdown
    assert draft.synthesis_mode == "llm"
    assert draft.sections and draft.sections[0].heading == "What affects the price"
    channels = [m.channel for m in provider.requests[0]]
    assert channels[:2] == ["system", "developer_policy"]


async def test_without_a_model_the_draft_is_an_outline() -> None:
    draft = await generate_draft(_brief(), gateway=ModelGateway(provider=DeterministicProvider()))
    assert OUTLINE_NOTICE in draft.body_markdown and draft.synthesis_mode == "deterministic"
