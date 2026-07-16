"""Add complaint resolution, closing, and multi-reply workflow.

Revision ID: 0006_complaint_workflow
Revises: 0005_add_material_owner
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0006_complaint_workflow"
down_revision = "0005_add_material_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = {column["name"] for column in inspector.get_columns("complaints")}

    if "is_resolved" not in columns:
        op.add_column(
            "complaints",
            sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "resolved_at" not in columns:
        op.add_column("complaints", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    if "is_closed" not in columns:
        op.add_column(
            "complaints",
            sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "closed_at" not in columns:
        op.add_column("complaints", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    if "closed_by" not in columns:
        op.add_column(
            "complaints",
            sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )

    if "complaint_replies" not in inspect(conn).get_table_names():
        op.create_table(
            "complaint_replies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("complaint_id", sa.Integer(), sa.ForeignKey("complaints.id"), nullable=False),
            sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_complaint_replies_id", "complaint_replies", ["id"], unique=False)
        op.create_index(
            "ix_complaint_replies_complaint_id",
            "complaint_replies",
            ["complaint_id"],
            unique=False,
        )
        # Preserve existing one-off replies as the first message in each conversation.
        op.execute(sa.text(
            "INSERT INTO complaint_replies (complaint_id, admin_id, content, created_at) "
            "SELECT id, admin_id, reply, COALESCE(replied_at, created_at) FROM complaints "
            "WHERE reply IS NOT NULL AND reply <> '' AND admin_id IS NOT NULL"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if "complaint_replies" in inspector.get_table_names():
        index_names = {index["name"] for index in inspector.get_indexes("complaint_replies")}
        if "ix_complaint_replies_complaint_id" in index_names:
            op.drop_index("ix_complaint_replies_complaint_id", table_name="complaint_replies")
        if "ix_complaint_replies_id" in index_names:
            op.drop_index("ix_complaint_replies_id", table_name="complaint_replies")
        op.drop_table("complaint_replies")

    columns = {column["name"] for column in inspect(conn).get_columns("complaints")}
    for column in ("closed_by", "closed_at", "is_closed", "resolved_at", "is_resolved"):
        if column in columns:
            op.drop_column("complaints", column)
