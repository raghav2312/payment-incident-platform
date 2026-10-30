"""Expand allowed payment statuses

Revision ID: a71f42c532f5
Revises: 76f3c96a1341
Create Date: 2026-10-30 15:46:28.789619

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a71f42c532f5'
down_revision: Union[str, Sequence[str], None] = '76f3c96a1341'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow processing and unknown payment statuses."""
    op.drop_constraint(
        "ck_payments_valid_status",
        "payments",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payments_valid_status",
        "payments",
        "status IN ('pending', 'processing', 'succeeded', 'failed', 'unknown')",
    )


def downgrade() -> None:
    """Restore the original allowed payment statuses."""
    # This fails if existing payments still use processing or unknown.
    op.drop_constraint(
        "ck_payments_valid_status",
        "payments",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payments_valid_status",
        "payments",
        "status IN ('pending', 'succeeded', 'failed')",
    )
