"""In-process metrics registry.

Deliberately dependency-free: counters, gauges and histograms held in memory and
exposed both as JSON (for the API's ``/metrics`` route) and in Prometheus text
format.  A Prometheus client or OTLP exporter can replace the backend without
any call site changing, because everything goes through :func:`counter`,
:func:`gauge` and :func:`observe`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

#: The metric names the Build Specification requires (section 48).
REQUIRED_METRICS: tuple[str, ...] = (
    "agent_runs_total",
    "agent_failures_total",
    "agent_latency_ms",
    "agent_cost_usd",
    "workflow_duration_ms",
    "workflow_failures_total",
    "crawl_pages_total",
    "crawl_errors_total",
    "recommendations_created_total",
    "recommendations_approved_total",
    "actions_executed_total",
    "actions_failed_total",
)

_BUCKETS_MS = (10, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000)


def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted((labels or {}).items()))


@dataclass
class _Histogram:
    count: int = 0
    total: float = 0.0
    buckets: dict[float, int] = field(default_factory=lambda: dict.fromkeys(_BUCKETS_MS, 0))

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        for bound in _BUCKETS_MS:
            if value <= bound:
                self.buckets[bound] += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[Any, float] = {}
        self._gauges: dict[Any, float] = {}
        self._histograms: dict[Any, _Histogram] = {}

    def counter(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            key = _key(name, labels)
            self._counters[key] = self._counters.get(key, 0.0) + value

    def gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[_key(name, labels)] = value

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            key = _key(name, labels)
            self._histograms.setdefault(key, _Histogram()).observe(value)

    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": [
                    {"name": n, "labels": dict(lbls), "value": v}
                    for (n, lbls), v in sorted(self._counters.items())
                ],
                "gauges": [
                    {"name": n, "labels": dict(lbls), "value": v}
                    for (n, lbls), v in sorted(self._gauges.items())
                ],
                "histograms": [
                    {
                        "name": n,
                        "labels": dict(lbls),
                        "count": h.count,
                        "sum": round(h.total, 4),
                        "avg": round(h.total / h.count, 4) if h.count else 0.0,
                        "buckets": {str(k): v for k, v in h.buckets.items()},
                    }
                    for (n, lbls), h in sorted(self._histograms.items())
                ],
            }

    def render_prometheus(self) -> str:
        lines: list[str] = []

        def fmt(
            name: str, labels: tuple[tuple[str, str], ...], value: float, suffix: str = ""
        ) -> str:
            label_str = ""
            if labels:
                inner = ",".join(f'{k}="{v}"' for k, v in labels)
                label_str = f"{{{inner}}}"
            return f"{name}{suffix}{label_str} {value}"

        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(fmt(name, labels, value))
            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(fmt(name, labels, value))
            for (name, labels), hist in sorted(self._histograms.items()):
                for bound, count in hist.buckets.items():
                    bucket_labels = (*labels, ("le", str(bound)))
                    lines.append(fmt(name, bucket_labels, count, "_bucket"))
                lines.append(fmt(name, labels, hist.total, "_sum"))
                lines.append(fmt(name, labels, hist.count, "_count"))
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


_registry = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _registry


def counter(name: str, value: float = 1.0, **labels: str) -> None:
    _registry.counter(name, value, **labels)


def gauge(name: str, value: float, **labels: str) -> None:
    _registry.gauge(name, value, **labels)


def observe(name: str, value: float, **labels: str) -> None:
    _registry.observe(name, value, **labels)


@contextmanager
def timed(name: str, **labels: str) -> Iterator[None]:
    """Record elapsed milliseconds into a histogram, success or failure."""
    started = time.perf_counter()
    try:
        yield
    finally:
        observe(name, (time.perf_counter() - started) * 1000.0, **labels)


__all__ = [
    "REQUIRED_METRICS",
    "MetricsRegistry",
    "counter",
    "gauge",
    "get_registry",
    "observe",
    "timed",
]
