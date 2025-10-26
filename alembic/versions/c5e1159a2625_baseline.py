"""baseline

Revision ID: c5e1159a2625
Revises:
Create Date: 2025-10-26 00:07:30.041256

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5e1159a2625"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client", sa.Text(), nullable=False),
        sa.Column("client_key", sa.Text(), nullable=False),
        sa.Column("start_iso", sa.Text(), nullable=False),
        sa.Column("end_iso", sa.Text(), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounded_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounded_hours", sa.Text(), nullable=False, server_default="0.00"),
        sa.Column("elapsed_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invoice_number", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("entries")
