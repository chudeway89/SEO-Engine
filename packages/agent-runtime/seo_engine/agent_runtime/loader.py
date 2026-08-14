"""Sibling-module loading for agents.

Agent directories are not importable packages (``agents/content/writer/`` is not
a valid identifier path), so an agent loads its own ``schemas.py`` by file path.

Doing that correctly is subtle: a module loaded with ``module_from_spec`` must be
registered in ``sys.modules`` *before* it is executed, or Pydantic cannot resolve
the model's own type annotations and every model raises
``class-not-fully-defined``.  This helper gets it right once so that all 35
agents do not each get it wrong.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from seo_engine.shared.errors import ValidationError


def load_agent_module(agent_file: str | Path, module_file: str = "schemas.py") -> ModuleType:
    """Load a module that sits next to an agent's ``agent.py``.

    Parameters
    ----------
    agent_file:
        Pass ``__file__`` from the agent module.
    module_file:
        The sibling file to load, ``schemas.py`` by default.
    """
    agent_path = Path(agent_file).resolve()
    target = agent_path.parent / module_file
    if not target.is_file():
        raise ValidationError(
            f"agent module {module_file!r} not found next to {agent_path.name}",
            {"expected": str(target)},
        )

    # A stable, collision-free name derived from the agent's directory.
    module_name = f"seo_engine_agents.{agent_path.parent.name.replace('-', '_')}.{target.stem}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery
        raise ValidationError(f"could not load {target}", {"module": module_name})

    module = importlib.util.module_from_spec(spec)
    # Registered *before* execution so Pydantic can resolve annotations that
    # refer back to this module's own namespace.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


__all__ = ["load_agent_module"]
