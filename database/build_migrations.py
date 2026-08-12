"""Regenerate the domain-by-domain migration history from the ORM models.

The migration chain is authored one domain at a time so that the history mirrors
the Build Specification (``0001_identity``, ``0002_brands`` …) instead of a
single unreadable "initial" revision.

Usage (destructive — drops and rebuilds the target database):

    python database/build_migrations.py

It is a developer tool, not something that runs in CI or production.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSIONS_DIR = REPO_ROOT / "database" / "migrations" / "versions"

#: (revision id, message, tables)
DOMAINS: list[tuple[str, str, list[str]]] = [
    (
        "0001",
        "identity",
        [
            "tenants",
            "users",
            "tenant_users",
            "roles",
            "subscription_plans",
            "entitlements",
            "usage_events",
        ],
    ),
    (
        "0002",
        "brands",
        [
            "brands",
            "brand_goals",
            "brand_services",
            "brand_products",
            "brand_audiences",
            "brand_locations",
            "brand_claims",
            "brand_voice_profiles",
            "brand_competitors",
            "competitor_observations",
            "projects",
        ],
    ),
    (
        "0003",
        "websites",
        [
            "websites",
            "crawl_jobs",
            "crawl_pages",
            "pages",
            "page_links",
            "page_images",
            "page_schema",
            "page_issues",
            "website_scorecards",
        ],
    ),
    (
        "0004",
        "search",
        [
            "keyword_clusters",
            "keywords",
            "keyword_variants",
            "keyword_metrics",
            "keyword_rankings",
            "serp_snapshots",
            "serp_results",
            "search_intents",
            "search_questions",
        ],
    ),
    (
        "0005",
        "content",
        [
            "content_assets",
            "content_versions",
            "content_briefs",
            "content_research",
            "content_sources",
            "content_evaluations",
            "content_representation",
            "content_repairs",
        ],
    ),
    (
        "0006",
        "agents",
        [
            "agents",
            "agent_capabilities",
            "agent_tools",
            "agent_runs",
            "agent_messages",
            "agent_outputs",
            "llm_usage",
        ],
    ),
    (
        "0007",
        "missions",
        [
            "missions",
            "tasks",
            "task_dependencies",
            "mission_tasks",
            "mission_metrics",
            "mission_progress",
        ],
    ),
    (
        "0008",
        "memory",
        ["memories", "memory_embeddings", "knowledge_nodes", "knowledge_edges"],
    ),
    (
        "0009",
        "decision",
        [
            "evidence",
            "evidence_relationships",
            "opportunities",
            "recommendations",
            "actions",
            "action_approvals",
            "action_outcomes",
            "experiments",
            "policies",
        ],
    ),
    (
        "0010",
        "integrations",
        [
            "integration_connections",
            "integration_credentials",
            "provider_raw_responses",
            "gsc_connections",
            "gsc_properties",
            "gsc_performance",
            "gsc_inspections",
            "gsc_sitemaps",
            "ga4_connections",
            "ga4_properties",
            "ga4_metrics",
            "ga4_conversions",
        ],
    ),
    ("0011", "events_audit", ["events", "audit_logs"]),
]


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ, **(env or {})})
    if result.returncode != 0:
        sys.exit(result.returncode)


EXTENSION_BOOTSTRAP = (
    "def upgrade() -> None:\n"
    "    # Required extensions.  pgvector backs semantic memory retrieval.\n"
    '    op.execute("CREATE EXTENSION IF NOT EXISTS vector")\n'
    '    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")\n'
)


def patch_generated(revision: str) -> None:
    """Apply the fix-ups autogenerate cannot infer.

    * the pgvector column type needs its module imported;
    * the first revision must create the required PostgreSQL extensions.
    """
    for path in VERSIONS_DIR.glob(f"{revision}_*.py"):
        source = path.read_text()
        if "pgvector." in source and "import pgvector" not in source:
            source = source.replace(
                "from alembic import op",
                "import pgvector.sqlalchemy\nfrom alembic import op",
                1,
            )
        if revision == "0001":
            source = source.replace("def upgrade() -> None:\n", EXTENSION_BOOTSTRAP, 1)
        path.write_text(source)


def main() -> None:
    if VERSIONS_DIR.exists():
        shutil.rmtree(VERSIONS_DIR)
    VERSIONS_DIR.mkdir(parents=True)

    previous: str | None = None
    for revision, message, tables in DOMAINS:
        cmd = [
            sys.executable,
            "-m",
            "alembic",
            "revision",
            "--autogenerate",
            "-m",
            message,
            "--rev-id",
            revision,
        ]
        if previous:
            cmd += ["--head", previous]
        run(cmd, env={"ALEMBIC_TABLE_SCOPE": ",".join(tables)})
        patch_generated(revision)
        run([sys.executable, "-m", "alembic", "upgrade", revision])
        previous = revision

    print("\nMigration chain rebuilt:")
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
