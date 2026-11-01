"""A scripted model provider — a test double, never used outside tests.

It stands in for *any* model: it returns pre-written replies (or raises
pre-set failures) in order, so the model-written path, the fallback paths and
usage recording can be exercised without a network, an API key or any
particular vendor. It records every request so tests can assert the channel
layout and the parameters sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_engine.shared.llm import LLMMessage, LLMProvider, LLMResponse, LLMUsageRecord


@dataclass
class SentRequest:
    messages: list[LLMMessage]
    model: str
    max_tokens: int
    temperature: float | None


@dataclass
class ScriptedProvider(LLMProvider):
    """Replies with each item of ``script`` in turn; the last one repeats.

    An item is the reply text, or an exception to raise for that call.
    """

    script: list[str | Exception] | str = field(default_factory=list)
    stop_reason: str = "stop"
    report_usage: bool = True
    name: str = "scripted_test_double"
    sent: list[SentRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.script, str):
            self.script = [self.script]

    @property
    def requests(self) -> list[list[LLMMessage]]:
        return [r.messages for r in self.sent]

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        assert isinstance(self.script, list) and self.script, "the script is empty"
        self.sent.append(SentRequest(list(messages), model, max_tokens, temperature))
        index = min(len(self.sent) - 1, len(self.script) - 1)
        item: Any = self.script[index]
        if isinstance(item, Exception):
            raise item
        return LLMResponse(
            text=item,
            usage=LLMUsageRecord(
                provider=self.name,
                model=model,
                input_tokens=sum(len(m.content) // 4 for m in messages)
                if self.report_usage
                else None,
                output_tokens=len(item) // 4 if self.report_usage else None,
                cached_tokens=None,
                estimated_cost_usd=None,
                latency_ms=1,
                stop_reason=self.stop_reason,
            ),
            stop_reason=self.stop_reason,
        )


__all__ = ["ScriptedProvider", "SentRequest"]
