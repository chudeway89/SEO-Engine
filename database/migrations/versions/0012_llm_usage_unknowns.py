"""llm_usage: record unknown token counts and costs as unknown

A provider may not report token usage, and the platform ships no price list
(the operator configures prices for the model they connected). An unreported
count or an unpriced call was previously forced to 0, which reads as a real
figure. These columns now accept NULL, meaning "not known". The stop reason is
recorded so a completion cut off at the output limit is visible.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNKNOWABLE = (
    ("input_tokens", sa.Integer()),
    ("output_tokens", sa.Integer()),
    ("cached_tokens", sa.Integer()),
    ("estimated_cost_usd", sa.Float()),
)


def upgrade() -> None:
    for column, type_ in _UNKNOWABLE:
        op.alter_column("llm_usage", column, existing_type=type_, nullable=True)
    op.add_column("llm_usage", sa.Column("stop_reason", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_usage", "stop_reason")
    for column, type_ in _UNKNOWABLE:
        op.execute(sa.text(f"UPDATE llm_usage SET {column} = 0 WHERE {column} IS NULL"))
        op.alter_column("llm_usage", column, existing_type=type_, nullable=False)
