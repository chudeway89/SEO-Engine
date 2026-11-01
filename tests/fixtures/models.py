"""A scripted model provider — a test double, never used outside tests.

It returns pre-written text so the model-written path (the writer's prose, the
hybrid synthesis label, usage recording) can be exercised without a network or
an API key. It records every request so tests can assert the channel layout.
"""

from __future__ import annotations

from seo_engine.shared.llm import LLMMessage, LLMProvider, LLMResponse, LLMUsageRecord


class ScriptedProvider(LLMProvider):
    name = "scripted_test_double"

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[list[LLMMessage]] = []

    async def complete(
        self, messages: list[LLMMessage], *, model: str, temperature: float, max_tokens: int
    ) -> LLMResponse:
        self.requests.append(list(messages))
        return LLMResponse(
            text=self.text,
            usage=LLMUsageRecord(
                provider=self.name,
                model=model,
                input_tokens=sum(len(m.content) // 4 for m in messages),
                output_tokens=len(self.text) // 4,
                cached_tokens=0,
                estimated_cost_usd=0.0,
                latency_ms=1,
            ),
            stop_reason="end_turn",
        )


__all__ = ["ScriptedProvider"]
