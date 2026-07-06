"""add knowledge.entities + knowledge.entity_relations（实体级知识图谱）

实体图谱：从 PRD 抽取字段/章节/规则/概念等实体及其关系（局部优先/互斥/约束等），
支持多跳查询，根治 v5 审计 类A 全局错套 + 类B 概念混淆。

Revision ID: 018
Revises: 017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("knowledge.documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("system_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("canonical_key", sa.String(200), nullable=False),
        sa.Column("section_ref", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source_quote", sa.Text, nullable=True),
        sa.Column("attributes", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="knowledge",
    )
    op.create_index("ix_entities_doc_type", "entities", ["document_id", "entity_type"], schema="knowledge")
    op.create_index("ix_entities_sys_key", "entities", ["system_id", "canonical_key"], schema="knowledge")

    op.create_table(
        "entity_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", UUID(as_uuid=True), sa.ForeignKey("knowledge.entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_id", UUID(as_uuid=True), sa.ForeignKey("knowledge.entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("source_quote", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source_entity_id != target_entity_id", name="ck_no_self_entity_relation"),
        schema="knowledge",
    )
    op.create_index("ix_entity_relations_source", "entity_relations", ["source_entity_id"], schema="knowledge")
    op.create_index("ix_entity_relations_target", "entity_relations", ["target_entity_id"], schema="knowledge")
    op.create_index("ix_entity_relations_doc_type", "entity_relations", ["document_id", "relation_type"], schema="knowledge")


def downgrade() -> None:
    op.drop_table("entity_relations", schema="knowledge")
    op.drop_table("entities", schema="knowledge")
