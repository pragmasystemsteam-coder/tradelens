"""Setup engine document: what the worker needs to re-evaluate a stored setup (task 2.3).

``setups.engine`` holds the candidate (with its higher-timeframe context) and the factors with
their template values, so batch-end re-evaluation and the rewritten explanation work on a
setup saved by an earlier close or before a restart. It changes with each revision, like the
score columns; the identity columns stay guarded by ``setups_guard``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``setups.engine``."""
    op.execute("ALTER TABLE setups ADD COLUMN engine jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    """Drop ``setups.engine``."""
    op.execute("ALTER TABLE setups DROP COLUMN IF EXISTS engine")
