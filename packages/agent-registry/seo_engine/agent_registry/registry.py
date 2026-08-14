"""Agent registry.

Agents are discovered by scanning ``agents/**/manifest.yaml``.  Each manifest is
validated against :class:`AgentManifest` and its implementation module is loaded
lazily by path.  Loading by path rather than by import name is deliberate: it
lets the on-disk layout follow the Build Specification exactly
(``agents/content/writer/agent.py``) without every directory having to be a
valid Python identifier.

The registry is the single source of truth for *what an agent is allowed to do*.
The runner consults it before every execution; nothing else may.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml
from seo_engine.observability.logging import get_logger
from seo_engine.schemas.agent import AgentContext, AgentManifest, AgentResult
from seo_engine.shared.errors import AgentNotFoundError, ValidationError

log = get_logger(__name__)


@runtime_checkable
class Agent(Protocol):
    """The execution contract every agent implements (Architecture Pack §71)."""

    manifest: AgentManifest

    async def execute(self, context: AgentContext) -> AgentResult: ...


@dataclass(slots=True)
class AgentEntry:
    manifest: AgentManifest
    manifest_path: Path
    module_path: Path
    _instance: Any = None

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def category(self) -> str:
        """Directory group, e.g. ``seo`` for ``agents/seo/technical/``."""
        return self.manifest_path.parent.parent.name


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking up to the directory holding `agents/`."""
    from seo_engine.shared.config import get_settings

    configured = get_settings().repo_root
    if configured:
        return Path(configured)

    current = (start or Path(__file__)).resolve()
    for parent in [current, *current.parents]:
        if (parent / "agents").is_dir() and (parent / "pyproject.toml").is_file():
            return parent
    raise ValidationError("could not locate the repository root; set REPO_ROOT explicitly", {})


class AgentRegistry:
    """Discovers, validates and instantiates agents."""

    def __init__(self, agents_dir: Path | None = None) -> None:
        self._agents_dir = agents_dir
        self._entries: dict[str, AgentEntry] = {}
        self._by_capability: dict[str, list[str]] = {}
        self._loaded = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def agents_dir(self) -> Path:
        if self._agents_dir is None:
            self._agents_dir = find_repo_root() / "agents"
        return self._agents_dir

    def load(self, *, force: bool = False) -> AgentRegistry:
        with self._lock:
            if self._loaded and not force:
                return self
            self._entries.clear()
            self._by_capability.clear()

            root = self.agents_dir
            if not root.is_dir():
                log.warning("agent_registry_no_directory", path=str(root))
                self._loaded = True
                return self

            for manifest_path in sorted(root.glob("**/manifest.yaml")):
                try:
                    entry = self._load_manifest(manifest_path)
                except Exception as exc:
                    log.error("agent_manifest_invalid", path=str(manifest_path), error=str(exc))
                    raise ValidationError(
                        f"invalid agent manifest: {manifest_path.relative_to(root.parent)}",
                        {"error": str(exc)},
                    ) from exc

                if entry.id in self._entries:
                    raise ValidationError(
                        f"duplicate agent id {entry.id}",
                        {
                            "first": str(self._entries[entry.id].manifest_path),
                            "second": str(manifest_path),
                        },
                    )
                self._entries[entry.id] = entry
                for capability in entry.manifest.capabilities:
                    self._by_capability.setdefault(capability, []).append(entry.id)

            self._loaded = True
            log.info("agent_registry_loaded", agents=len(self._entries), path=str(root))
            return self

    def _load_manifest(self, path: Path) -> AgentEntry:
        raw = yaml.safe_load(path.read_text()) or {}
        manifest = AgentManifest.model_validate(raw)
        module_path = path.parent / manifest.module
        if not module_path.is_file():
            raise ValidationError(
                f"manifest points at a missing module: {manifest.module}",
                {"agent_id": manifest.id, "expected": str(module_path)},
            )
        return AgentEntry(manifest=manifest, manifest_path=path, module_path=module_path)

    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._entries)

    def __iter__(self) -> Iterator[AgentEntry]:
        self._ensure_loaded()
        return iter(self._entries.values())

    def __contains__(self, agent_id: str) -> bool:
        self._ensure_loaded()
        return agent_id in self._entries

    def ids(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._entries)

    def entry(self, agent_id: str) -> AgentEntry:
        self._ensure_loaded()
        entry = self._entries.get(agent_id)
        if entry is None:
            raise AgentNotFoundError(
                f"no agent registered with id {agent_id!r}",
                {"agent_id": agent_id, "known": sorted(self._entries)[:20]},
            )
        return entry

    def manifest(self, agent_id: str) -> AgentManifest:
        return self.entry(agent_id).manifest

    def find_by_capability(self, capability: str) -> list[AgentManifest]:
        self._ensure_loaded()
        return [self._entries[a].manifest for a in self._by_capability.get(capability, [])]

    def capabilities(self) -> dict[str, list[str]]:
        self._ensure_loaded()
        return {cap: sorted(ids) for cap, ids in sorted(self._by_capability.items())}

    # ------------------------------------------------------------------
    def get(self, agent_id: str) -> Agent:
        """Instantiate (once) and return the agent implementation."""
        entry = self.entry(agent_id)
        if entry._instance is None:
            entry._instance = self._instantiate(entry)
        return entry._instance  # type: ignore[return-value]

    def _instantiate(self, entry: AgentEntry) -> Agent:
        module_name = f"seo_engine_agents.{entry.id.lower().replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entry.module_path)
        if spec is None or spec.loader is None:  # pragma: no cover - import machinery
            raise ValidationError(
                f"could not load agent module for {entry.id}",
                {"path": str(entry.module_path)},
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        factory = getattr(module, "AGENT", None)
        if factory is None:
            raise ValidationError(
                f"agent module for {entry.id} does not define AGENT",
                {"path": str(entry.module_path)},
            )
        # AGENT may be a class or an already-built instance.  Checking for an
        # `execute` attribute is not enough: a class exposes the unbound method too.
        instance = factory() if isinstance(factory, type) else factory

        if not hasattr(instance, "execute"):
            raise ValidationError(
                f"agent {entry.id} does not implement execute()", {"agent_id": entry.id}
            )
        # The manifest on disk is authoritative; an implementation cannot widen
        # its own permissions by declaring a different one in code.
        instance.manifest = entry.manifest
        return instance  # type: ignore[return-value]

    # ------------------------------------------------------------------
    async def sync_to_database(self, session: Any) -> int:
        """Mirror the on-disk manifests into the ``agents`` catalogue tables."""
        from seo_engine.domain.models.agents import (
            AgentCapabilityRecord,
            AgentRecord,
            AgentToolRecord,
        )
        from sqlalchemy import select

        self._ensure_loaded()
        synced = 0
        for entry in self._entries.values():
            manifest = entry.manifest
            existing = await session.execute(
                select(AgentRecord).where(AgentRecord.agent_id == manifest.id)
            )
            record = existing.scalar_one_or_none()
            payload = {
                "name": manifest.name,
                "version": manifest.version,
                "agent_type": entry.category,
                "description": manifest.description,
                "model_policy": manifest.model_policy.model_dump(mode="json"),
                "risk_level": manifest.risk_level.value,
                "manifest": manifest.model_dump(mode="json"),
                "manifest_path": str(entry.manifest_path),
                "status": "active",
            }
            if record is None:
                session.add(AgentRecord(agent_id=manifest.id, **payload))
            else:
                for key, value in payload.items():
                    setattr(record, key, value)

            for grant in manifest.permissions:
                found = await session.execute(
                    select(AgentCapabilityRecord).where(
                        AgentCapabilityRecord.agent_id == manifest.id,
                        AgentCapabilityRecord.capability == grant.capability,
                    )
                )
                cap = found.scalar_one_or_none()
                if cap is None:
                    session.add(
                        AgentCapabilityRecord(
                            agent_id=manifest.id,
                            capability=grant.capability,
                            permission=grant.permission.value,
                        )
                    )
                else:
                    cap.permission = grant.permission.value

            for tool in manifest.tools:
                found = await session.execute(
                    select(AgentToolRecord).where(
                        AgentToolRecord.agent_id == manifest.id, AgentToolRecord.tool == tool
                    )
                )
                if found.scalar_one_or_none() is None:
                    session.add(AgentToolRecord(agent_id=manifest.id, tool=tool))

            synced += 1
        await session.flush()
        return synced


_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def set_registry(registry: AgentRegistry | None) -> None:
    global _registry
    _registry = registry


__all__ = [
    "Agent",
    "AgentEntry",
    "AgentRegistry",
    "find_repo_root",
    "get_registry",
    "set_registry",
]
