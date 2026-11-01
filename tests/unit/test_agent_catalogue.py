"""The agent catalogue and the mission graph, checked as data.

These guard the properties that make the catalogue trustworthy as it grows:
every agent is fully documented and loadable, every mission stage is served by
an agent that declares the stage's capabilities, every stage is created after
everything it depends on, and no agent exists without a place in a mission —
except the orchestrator, which plans missions rather than being a stage of one
(Rule 15: no agent exists merely for coverage).
"""

from __future__ import annotations

import pytest
import yaml
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root
from seo_engine.orchestration.orchestrator import (
    MISSION_STAGES,
    MISSION_TARGET_METRIC,
    SEED_STAGES,
    STAGE_SPECS,
)
from seo_engine.workflows.steps import SEED_STAGES as STEP_SEED_STAGES

AGENTS = find_repo_root() / "agents"
#: The planner is not a stage of the plans it makes.
NOT_A_STAGE = {"ORCH-001"}


@pytest.fixture(scope="module")
def registry() -> AgentRegistry:
    return AgentRegistry(AGENTS).load(force=True)


def test_every_agent_directory_is_complete() -> None:
    manifests = sorted(AGENTS.glob("*/*/manifest.yaml"))
    assert len(manifests) == 36
    for manifest in manifests:
        directory = manifest.parent
        for required in ("agent.py", "README.md", "prompt.md"):
            assert (directory / required).is_file(), f"{directory.name} lacks {required}"


def test_the_registry_loads_every_agent_with_a_unique_id(registry: AgentRegistry) -> None:
    assert len(registry) == 36


def test_every_stage_is_served_by_an_agent_that_declares_its_capabilities(
    registry: AgentRegistry,
) -> None:
    for name, spec in STAGE_SPECS.items():
        manifest = registry.manifest(spec.agent_id)
        missing = set(spec.capabilities) - set(manifest.capabilities)
        assert not missing, f"{name}: {spec.agent_id} does not declare {missing}"
        assert set(spec.tools) <= set(manifest.tools), f"{name}: tools beyond the manifest"


def test_every_mission_creates_stages_after_their_dependencies() -> None:
    for mission, stages in MISSION_STAGES.items():
        assert mission in MISSION_TARGET_METRIC
        for index, stage in enumerate(stages):
            spec = STAGE_SPECS[stage]
            for dependency in [*spec.depends_on, *spec.after]:
                if dependency in stages:
                    assert stages.index(dependency) < index, (
                        f"{mission}: {stage} is listed before its dependency {dependency}"
                    )


def test_every_agent_but_the_planner_has_a_place_in_some_mission(
    registry: AgentRegistry,
) -> None:
    used_stages = {s for stages in MISSION_STAGES.values() for s in stages}
    assert set(STAGE_SPECS) == used_stages, "every defined stage is used by some mission"

    staged = {STAGE_SPECS[s].agent_id for s in used_stages}
    ids = {yaml.safe_load(p.read_text())["id"] for p in AGENTS.glob("*/*/manifest.yaml")}
    assert ids - staged == NOT_A_STAGE
    assert all(registry.manifest(agent_id) for agent_id in staged)


def test_seed_stages_agree_between_orchestrator_and_workflow() -> None:
    assert SEED_STAGES == STEP_SEED_STAGES
    assert set(SEED_STAGES) <= set(STAGE_SPECS)
    assert set(SEED_STAGES) <= set(STAGE_SPECS["opportunity_detection"].after)
