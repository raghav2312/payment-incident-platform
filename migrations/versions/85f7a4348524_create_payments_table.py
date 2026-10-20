"""Create payments table

Revision ID: 85f7a4348524
Revises:
Create Date: 2026-10-20 16:10:04.681444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85f7a4348524'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "customer_reference",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_payments_positive_amount",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_payments_valid_status",
        ),
        sa.CheckConstraint(
            "currency = 'CAD'",
            name="ck_payments_cad_currency",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_payments_customer_reference",
        "payments",
        ["customer_reference"],
        unique=False,
    )
    op.create_index(
        "ix_payments_status",
        "payments",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index(
        "ix_payments_customer_reference",
        table_name="payments",
    )
    op.drop_table("payments")
