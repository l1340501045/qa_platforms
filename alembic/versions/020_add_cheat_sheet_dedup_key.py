"""add stable dedup_key for cheat sheet items

Revision ID: 020
Revises: 019
"""

import sqlalchemy as sa

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cheat_sheet_items", sa.Column("dedup_key", sa.String(length=200), nullable=True), schema="knowledge")
    op.execute("UPDATE knowledge.cheat_sheet_items SET dedup_key = 'legacy:' || id::text WHERE dedup_key IS NULL")
    op.execute("""
        UPDATE knowledge.cheat_sheet_items AS item
        SET dedup_key = item.sheet_type || ':' ||
            LEAST(source_entity.canonical_key, target_entity.canonical_key) || '|' ||
            GREATEST(source_entity.canonical_key, target_entity.canonical_key) || '|' ||
            relation.relation_type
        FROM knowledge.entity_relations AS relation
        JOIN knowledge.entities AS source_entity ON source_entity.id = relation.source_entity_id
        JOIN knowledge.entities AS target_entity ON target_entity.id = relation.target_entity_id
        WHERE item.sheet_type IN ('confusion_pair', 'section_priority')
          AND item.source_relation_ids IS NOT NULL
          AND relation.id::text = item.source_relation_ids->>0
    """)
    op.execute("""
        UPDATE knowledge.cheat_sheet_items AS item
        SET dedup_key = 'must_test:' || rule_entity.canonical_key || '|' || target_entity.canonical_key
        FROM knowledge.entities AS rule_entity,
             knowledge.entities AS target_entity
        WHERE item.sheet_type = 'must_test'
          AND item.source_entity_ids IS NOT NULL
          AND rule_entity.id::text = item.source_entity_ids->>0
          AND target_entity.id::text = item.source_entity_ids->>1
          AND rule_entity.entity_type = 'rule'
    """)
    op.execute("""
        UPDATE knowledge.cheat_sheet_items AS item
        SET dedup_key = CASE
            WHEN relation.relation_type = 'transitions_to' THEN
                'prd_status:state_transition:' ||
                LEAST(source_entity.canonical_key, target_entity.canonical_key) || '|' ||
                GREATEST(source_entity.canonical_key, target_entity.canonical_key)
            ELSE
                'prd_status:unreachable:' || source_entity.canonical_key
            END
        FROM knowledge.entity_relations AS relation
        JOIN knowledge.entities AS source_entity ON source_entity.id = relation.source_entity_id
        JOIN knowledge.entities AS target_entity ON target_entity.id = relation.target_entity_id
        WHERE item.sheet_type = 'prd_status'
          AND item.source_relation_ids IS NOT NULL
          AND relation.id::text = item.source_relation_ids->>0
    """)
    op.alter_column("cheat_sheet_items", "dedup_key", nullable=False, schema="knowledge")
    op.create_index(
        "ix_cheat_sheet_items_sheet_dedup",
        "cheat_sheet_items",
        ["sheet_id", "dedup_key"],
        unique=False,
        schema="knowledge",
    )
    op.create_unique_constraint(
        "uq_cheat_sheets_document_version",
        "cheat_sheets",
        ["document_id", "version"],
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_constraint("uq_cheat_sheets_document_version", "cheat_sheets", schema="knowledge", type_="unique")
    op.drop_index("ix_cheat_sheet_items_sheet_dedup", table_name="cheat_sheet_items", schema="knowledge")
    op.drop_column("cheat_sheet_items", "dedup_key", schema="knowledge")
