"""Golden-dataset evaluation of agent behaviour.

Each case in ``golden/*.json`` runs one agent through the real runtime against
a brand graph built through the real domain services, and asserts the
behaviours that agent's README lists under "Evaluation criteria". A regression
names the dataset, the case and the exact property that changed.
"""

from __future__ import annotations

import pytest
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root, set_registry
from sqlalchemy.ext.asyncio import AsyncSession

from tests.evaluation.harness import check, load_cases, resolve, run_case

pytestmark = [pytest.mark.integration]

CASES = load_cases()


@pytest.fixture(scope="module", autouse=True)
def _registry() -> None:
    set_registry(AgentRegistry(find_repo_root() / "agents").load(force=True))


def test_the_golden_datasets_exist_and_are_non_trivial() -> None:
    files = {stem for stem, *_ in CASES}
    assert "brand_understanding" in files, "BRD-001's README cites this dataset"
    assert len(CASES) >= 15
    for stem, name, _, case in CASES:
        assert case["expect"], f"{stem}/{name} asserts nothing"


@pytest.mark.parametrize(
    ("stem", "name", "header", "case"),
    CASES,
    ids=[f"{stem}:{name}" for stem, name, _, _ in CASES],
)
async def test_golden_case(
    session: AsyncSession, tenant_ctx, stem: str, name: str, header: dict, case: dict
) -> None:
    _, _, principal = tenant_ctx
    failures = await run_case(session, principal, header, dict(case))
    assert not failures, f"{stem}/{name}: " + "; ".join(failures)


def test_the_checker_reports_exactly_what_failed() -> None:
    document = {"outputs": {"items": ["a", "b"], "score": 3}, "limitations": ["No goals recorded"]}
    assert (
        check(document, {"path": "outputs.items", "op": "before", "value": "a", "other": "b"})
        is None
    )
    assert check(document, {"path": "limitations", "op": "any_contains", "value": "goals"}) is None
    assert "failed" in check(document, {"path": "outputs.score", "op": "gt", "value": 5})
    assert (
        check(document, {"path": "outputs.nope", "op": "eq", "value": 1}) == "outputs.nope: missing"
    )
    assert resolve(document, "outputs.items.1") == "b"
