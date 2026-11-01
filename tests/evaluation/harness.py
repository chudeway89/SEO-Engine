"""The golden-dataset harness.

A golden file is a list of cases for one agent. Each case declares a brand graph
and the integrations to connect, the agent's inputs, and the expectations its
result must meet. The harness builds the brand through the real domain services,
runs the agent through the real Agent Runtime, and checks each expectation
against ``AgentResult.model_dump(mode="json")``.

Expectations are deliberately simple and explicit, so a failing case names the
exact property that regressed:

``eq`` · ``len`` · ``contains`` · ``not_contains`` · ``any_contains`` ·
``none_contains`` · ``gt`` · ``lt`` · ``before`` (``value`` precedes ``other`` in
a list) · ``empty`` · ``not_empty``

Paths are dotted, with integer segments indexing lists
(``outputs.strategy.stages.0.stage``).
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

from seo_engine.domain.services import BrandService, IntegrationService
from seo_engine.permissions.rbac import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.agents import AgentHarness

GOLDEN = Path(__file__).parent / "golden"
_MISSING = object()


def load_cases() -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    """(file stem, case name, file header, case) for every golden case."""
    cases = []
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text())
        for case in data["cases"]:
            cases.append((path.stem, case["name"], data, case))
    return cases


async def build_brand(
    session: AsyncSession, principal: Principal, spec: dict[str, Any]
) -> uuid.UUID:
    brands = BrandService(session, principal)
    brand = await brands.create(
        name=spec.get("name", f"Golden {uuid.uuid4().hex[:6]}"),
        industry=spec.get("industry"),
        website=spec.get("website"),
        risk_category=spec.get("risk_category", "general"),
    )
    for goal in spec.get("goals", []):
        await brands.add_goal(brand.id, **goal)
    for service in spec.get("services", []):
        await brands.add_service(brand.id, **service)
    for audience in spec.get("audiences", []):
        await brands.add_audience(brand.id, **audience)
    for location in spec.get("locations", []):
        await brands.add_location(brand.id, **location)
    for competitor in spec.get("competitors", []):
        await brands.add_competitor(brand.id, **competitor)
    if spec.get("voice"):
        await brands.set_voice_profile(brand.id, **spec["voice"])
    for claim in spec.get("claims", []):
        approve = claim.pop("approve", False)
        record = await brands.add_claim(brand.id, **claim)
        if approve:
            await brands.approve_claim(record.id)
    integrations = IntegrationService(session, principal)
    for provider in spec.get("integrations", []):
        await integrations.connect(brand.id, provider)
    await session.flush()
    return brand.id


def resolve(document: Any, path: str) -> Any:
    current = document
    for segment in path.split(".") if path else []:
        if isinstance(current, list) and segment.lstrip("-").isdigit():
            index = int(segment)
            if not -len(current) <= index < len(current):
                return _MISSING
            current = current[index]
        elif isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return _MISSING
    return current


def check(document: dict[str, Any], expectation: dict[str, Any]) -> str | None:
    """Return a failure message, or ``None`` when the expectation holds."""
    path, op = expectation["path"], expectation["op"]
    value = expectation.get("value")
    actual = resolve(document, path)
    if actual is _MISSING:
        return f"{path}: missing"

    def text(item: Any) -> str:
        return item if isinstance(item, str) else json.dumps(item)

    ok: bool
    if op == "eq":
        ok = actual == value
    elif op == "len":
        ok = len(actual) == value
    elif op == "contains":
        ok = value in actual
    elif op == "not_contains":
        ok = value not in actual
    elif op in {"any_contains", "none_contains"} and not isinstance(actual, list):
        return f"{path}: {op} needs a list; use contains for a string"
    elif op == "any_contains":
        ok = any(value.lower() in text(item).lower() for item in actual)
    elif op == "none_contains":
        ok = not any(value.lower() in text(item).lower() for item in actual)
    elif op == "gt":
        ok = actual > value
    elif op == "lt":
        ok = actual < value
    elif op == "before":
        ok = (
            value in actual
            and expectation["other"] in actual
            and (actual.index(value) < actual.index(expectation["other"]))
        )
    elif op == "empty":
        ok = not actual
    elif op == "not_empty":
        ok = bool(actual)
    else:
        return f"{path}: unknown op {op!r}"
    return None if ok else f"{path} {op} {value!r} failed; actual: {actual!r}"


async def run_case(
    session: AsyncSession, principal: Principal, header: dict[str, Any], case: dict[str, Any]
) -> list[str]:
    case = copy.deepcopy(case)  # build_brand consumes parts of its spec
    brand_id = await build_brand(session, principal, case.get("brand", {}))
    harness = AgentHarness(session, principal, brand_id, None, client=None)
    outcome = await harness.run(case.get("agent_id", header["agent_id"]), case.get("inputs", {}))
    document = outcome.result.model_dump(mode="json")
    return [msg for e in case["expect"] if (msg := check(document, e)) is not None]


__all__ = ["GOLDEN", "build_brand", "check", "load_cases", "resolve", "run_case"]
