"""The ``seo-engine`` command-line tool.

A thin operator front door over things that already exist elsewhere, so there is
one obvious way to run each of them:

    seo-engine migrate          # alembic upgrade head
    seo-engine seed [--reset]   # create the demonstration tenant
    seo-engine serve            # run the API with uvicorn
    seo-engine worker           # run the worker process
    seo-engine agents           # list the loaded agents and their contracts
    seo-engine routes           # list the API routes

Each subcommand delegates to the real implementation; nothing here reimplements
behaviour that is tested elsewhere.
"""

from __future__ import annotations

import argparse
import sys


def _cmd_migrate(_: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    import asyncio

    from seo_engine.database.seed import seed
    from seo_engine.shared.db import dispose_engine

    async def _run() -> None:
        try:
            summary = await seed(reset=args.reset)
        finally:
            await dispose_engine()
        print(f"demo tenant ready: {summary['brand']} ({summary['brand_id']})")

    asyncio.run(_run())
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "seo_engine.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def _cmd_worker(_: argparse.Namespace) -> int:
    from seo_engine.worker.__main__ import main as worker_main

    worker_main()
    return 0


def _cmd_agents(_: argparse.Namespace) -> int:
    from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root

    registry = AgentRegistry(find_repo_root() / "agents").load()
    for agent_id in registry.ids():
        manifest = registry.manifest(agent_id)
        print(
            f"{manifest.id:10} {manifest.name:28} "
            f"risk={manifest.risk_level.value:8} "
            f"caps={','.join(manifest.capabilities)}"
        )
    print(f"\n{len(registry.ids())} agent(s) loaded.")
    return 0


def _cmd_routes(_: argparse.Namespace) -> int:
    import asyncio

    from seo_engine.api.main import create_app

    app = create_app()

    async def _collect() -> list[str]:
        # The OpenAPI schema is the materialised view of the route table; the
        # raw app.routes list holds lazy include objects in this FastAPI
        # version, so read the paths from the schema instead.
        async with app.router.lifespan_context(app):
            spec = app.openapi()
        lines: list[str] = []
        for path, methods in sorted(spec.get("paths", {}).items()):
            for method in sorted(methods):
                lines.append(f"{method.upper():6} {path}")
        return lines

    for line in asyncio.run(_collect()):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seo-engine", description="SEO Engine operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="run database migrations to head").set_defaults(
        func=_cmd_migrate
    )

    seed = sub.add_parser("seed", help="create the demonstration tenant")
    seed.add_argument("--reset", action="store_true", help="delete the existing demo tenant first")
    seed.set_defaults(func=_cmd_seed)

    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_cmd_serve)

    sub.add_parser("worker", help="run the worker process").set_defaults(func=_cmd_worker)
    sub.add_parser("agents", help="list loaded agents").set_defaults(func=_cmd_agents)
    sub.add_parser("routes", help="list API routes").set_defaults(func=_cmd_routes)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
