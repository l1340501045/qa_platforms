"""add CHECK constraints for self-association prevention"""

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # system_associations: 禁止自关联
    op.create_check_constraint(
        "ck_no_self_association",
        "system_associations",
        "source_system_id != target_system_id",
        schema="public",
    )
    # document_associations: 禁止自关联
    op.create_check_constraint(
        "ck_no_self_doc_association",
        "document_associations",
        "source_doc_id != target_doc_id",
        schema="knowledge",
    )


def downgrade():
    op.drop_constraint("ck_no_self_doc_association", "document_associations", schema="knowledge")
    op.drop_constraint("ck_no_self_association", "system_associations", schema="public")
