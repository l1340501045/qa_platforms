from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_engine, get_session_factory
from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
)
from src.platform_api.models.taxonomy import (
    TestCaseRelatedTaxonomyConcept as _CaseRelatedTaxonomyConcept,
)
from src.platform_api.models.testcase import TestBatch as BatchModel
from src.platform_api.models.testcase import TestCase as CaseModel
from src.platform_api.models.testcase import TestPoint as PointModel
from tests.platform_api.conftest import requires_db, set_taxonomy_immutability_triggers

pytestmark = requires_db


@pytest.fixture
async def db_session() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seeded_system(db_session: AsyncSession):
    system_id = uuid.uuid4()
    document_id = uuid.uuid4()
    content_hash = hashlib.sha256(str(document_id).encode()).hexdigest()
    system = System(id=system_id, name=f"taxonomy-test-{uuid.uuid4()}")
    document = Document(
        id=document_id,
        system_id=system_id,
        title="taxonomy migration test",
        doc_type="prd",
        content="# test",
        storage_path=f"test/{uuid.uuid4()}.md",
        content_hash=content_hash,
    )
    db_session.add(system)
    await db_session.flush()
    db_session.add(document)
    await db_session.commit()
    yield system_id, document_id

    await db_session.rollback()
    await set_taxonomy_immutability_triggers(db_session, enabled=False)
    try:
        await db_session.execute(
            delete(RequirementTaxonomyMapping).where(RequirementTaxonomyMapping.system_id == system_id)
        )
        await db_session.execute(delete(TaxonomyNode).where(TaxonomyNode.system_id == system_id))
        await db_session.execute(delete(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id))
        await db_session.execute(delete(TaxonomyConcept).where(TaxonomyConcept.system_id == system_id))
        await db_session.execute(delete(Document).where(Document.id == document_id))
        await db_session.execute(delete(System).where(System.id == system_id))
    finally:
        await set_taxonomy_immutability_triggers(db_session, enabled=True)
    await db_session.commit()


async def test_taxonomy_migration_adds_nullable_assignment_columns() -> None:
    async with get_engine().connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                table: {
                    column["name"]: column for column in inspect(sync_connection).get_columns(table, schema="testcase")
                }
                for table in ("test_batches", "test_points", "test_cases")
            }
        )

    assert columns["test_batches"]["taxonomy_version_id"]["nullable"] is True
    for table in ("test_points", "test_cases"):
        assert columns[table]["taxonomy_version_id"]["nullable"] is True
        assert columns[table]["taxonomy_concept_id"]["nullable"] is True
        assert columns[table]["taxonomy_resolution"]["nullable"] is True
    assert columns["test_points"]["taxonomy_selector_facts"]["nullable"] is True

    assert hasattr(BatchModel, "taxonomy_version_id")
    assert hasattr(PointModel, "taxonomy_concept_id")
    assert hasattr(CaseModel, "taxonomy_concept_id")


async def test_taxonomy_semantics_migration_preserves_v1_and_adds_v2_columns() -> None:
    async with get_engine().connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                table: {
                    column["name"]: column for column in inspect(sync_connection).get_columns(table, schema="testcase")
                }
                for table in ("taxonomy_versions", "taxonomy_nodes")
            }
        )

    assert columns["taxonomy_versions"]["schema_version"]["nullable"] is False
    assert "1" in str(columns["taxonomy_versions"]["schema_version"]["default"])
    assert columns["taxonomy_nodes"]["definition"]["nullable"] is True
    assert columns["taxonomy_nodes"]["scope_note"]["nullable"] is True
    assert columns["taxonomy_nodes"]["in_scope_examples"]["nullable"] is False
    assert columns["taxonomy_nodes"]["out_of_scope_examples"]["nullable"] is False
    assert hasattr(TaxonomyVersion, "schema_version")
    assert hasattr(TaxonomyNode, "definition")
    assert hasattr(TaxonomyNode, "in_scope_examples")


async def test_taxonomy_activation_review_migration_adds_nullable_audit_columns() -> None:
    async with get_engine().connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("taxonomy_versions", schema="testcase")
            }
        )

    for column_name in (
        "activation_review_id",
        "activation_package_hash",
        "activation_review_hash",
        "activation_review_artifact",
        "activation_rollback_plan",
    ):
        assert columns[column_name]["nullable"] is True
        assert hasattr(TaxonomyVersion, column_name)


async def test_database_rejects_initial_v2_activation_without_review_artifact(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="reviewed-module")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="valid semantics without review",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="受控模块",
            definition="具备完整语义定义。",
            scope_note="用于验证首次 v2 审核门禁。",
        )
    )
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    with pytest.raises(DBAPIError, match="initial v2 taxonomy activation review required"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_initial_v2_activation_with_unbound_review_artifact(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="invalid-reviewed-module")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="invalid review binding",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="受控模块",
            definition="具备完整语义定义。",
            scope_note="用于验证审核 artifact 绑定。",
        )
    )
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    version.activation_review_id = "review-001"
    version.activation_package_hash = "2" * 64
    version.activation_review_hash = "3" * 64
    version.activation_rollback_plan = "关闭 feature flag。"
    version.activation_review_artifact = {
        "package_hash": "2" * 64,
        "review_hash": "3" * 64,
        "package": {
            "system_id": str(system_id),
            "draft_manifest_hash": version.manifest_hash,
            "gate_status": "fail",
            "gold_review_method": "human_independent",
            "prepared_by": "builder",
            "evaluation_run_hash": "4" * 64,
        },
        "review": {
            "review_id": "review-001",
            "package_hash": "2" * 64,
            "draft_manifest_hash": version.manifest_hash,
            "evaluation_run_hash": "4" * 64,
            "decision": "approved",
            "reviewer": "reviewer",
        },
    }
    with pytest.raises(DBAPIError, match="initial v2 taxonomy activation review invalid"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_initial_v2_activation_with_missing_review_fields(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="missing-review-fields-module")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="missing review fields",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="受控模块",
            definition="具备完整语义定义。",
            scope_note="用于验证缺失审核字段不能利用 SQL NULL 绕过门禁。",
        )
    )
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    version.activation_review_id = "review-001"
    version.activation_package_hash = "2" * 64
    version.activation_review_hash = "3" * 64
    version.activation_rollback_plan = "关闭 feature flag。"
    version.activation_review_artifact = {
        "package_hash": "2" * 64,
        "review_hash": "3" * 64,
        "package": {
            "frozen_policy_hash": "4" * 64,
            "prepared_at": "2026-07-20T10:00:00+00:00",
        },
        "review": {"reviewed_at": "2026-07-20T10:05:00+00:00"},
    }
    with pytest.raises(DBAPIError, match="initial v2 taxonomy activation review invalid"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_v2_activation_without_grounded_capability_semantics(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="missing-evidence")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="invalid v2",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="capability",
            display_name="缺少语义证据",
            definition="缺少正向证据的能力定义。",
            scope_note="用于验证数据库激活门禁。",
        )
    )
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    with pytest.raises(DBAPIError, match="v2 active capability semantics required"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_empty_v2_taxonomy_activation(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="empty v2",
        created_by="author",
    )
    db_session.add(version)
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    with pytest.raises(DBAPIError, match="v2 taxonomy node semantics required"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_v2_module_without_definition_or_scope(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="undefined-module")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="undefined module",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="缺少定义的模块",
        )
    )
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    with pytest.raises(DBAPIError, match="v2 taxonomy node semantics required"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_v2_activation_with_invalid_example_shape(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="invalid-example-shape")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="invalid example shape",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="capability",
            display_name="示例格式无效",
            definition="包含格式无效的正向证据。",
            scope_note="用于验证数据库示例门禁。",
            in_scope_examples=[
                {
                    "text": "格式无效",
                    "document_content_hash": "invalid",
                    "requirement_unit_id": "invalid",
                }
            ],
        )
    )
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    with pytest.raises(DBAPIError, match="v2 taxonomy example invalid"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_treats_schema_version_as_immutable_version_identity(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="author",
    )
    db_session.add(version)
    await db_session.commit()

    version.schema_version = 2
    with pytest.raises(DBAPIError, match="taxonomy version identity/content is immutable"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_enforces_one_active_version_per_system(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    v1 = TaxonomyVersion(
        id=uuid.uuid4(),
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="test",
    )
    v2 = TaxonomyVersion(
        id=uuid.uuid4(),
        system_id=system_id,
        version=2,
        status="draft",
        manifest_hash="2" * 64,
        definition_hash="2" * 64,
        change_note="v2",
        created_by="test",
    )
    db_session.add_all([v1, v2])
    await db_session.commit()
    v1.status = "active"
    v1.activated_by = "reviewer"
    v1.activated_at = datetime.now(timezone.utc)
    await db_session.commit()

    v2.status = "active"
    v2.activated_by = "reviewer"
    v2.activated_at = datetime.now(timezone.utc)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("status", ["active", "retired"])
async def test_database_requires_new_taxonomy_version_to_start_as_draft(
    db_session: AsyncSession,
    seeded_system,
    status: str,
) -> None:
    system_id, _ = seeded_system
    db_session.add(
        TaxonomyVersion(
            system_id=system_id,
            version=1,
            status=status,
            manifest_hash="1" * 64,
            definition_hash="1" * 64,
            change_note="invalid initial state",
            created_by="author",
            activated_by="reviewer",
            activated_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(DBAPIError, match="taxonomy version must be inserted as draft"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_parent_from_another_taxonomy_version(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    parent = TaxonomyConcept(system_id=system_id, stable_key="parent")
    child = TaxonomyConcept(system_id=system_id, stable_key="child")
    v1 = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="test",
    )
    v2 = TaxonomyVersion(
        system_id=system_id,
        version=2,
        status="draft",
        manifest_hash="2" * 64,
        definition_hash="2" * 64,
        change_note="v2",
        created_by="test",
    )
    db_session.add_all([parent, child, v1, v2])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=v1.id,
            concept_id=parent.id,
            node_type="module",
            display_name="父节点",
        )
    )
    await db_session.commit()

    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=v2.id,
            concept_id=child.id,
            parent_concept_id=parent.id,
            node_type="capability",
            display_name="子节点",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    await db_session.execute(delete(TaxonomyNode).where(TaxonomyNode.system_id == system_id))
    await db_session.execute(delete(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id))
    await db_session.execute(delete(TaxonomyConcept).where(TaxonomyConcept.system_id == system_id))
    await db_session.commit()


async def test_database_rejects_batch_taxonomy_version_from_another_system(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, document_id = seeded_system
    other_system_id = uuid.uuid4()
    db_session.add(System(id=other_system_id, name=f"taxonomy-other-{uuid.uuid4()}"))
    await db_session.flush()
    other_version = TaxonomyVersion(
        system_id=other_system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="other system",
        created_by="test",
    )
    db_session.add(other_version)
    await db_session.flush()
    db_session.add(
        BatchModel(
            document_id=document_id,
            system_id=system_id,
            status="completed",
            taxonomy_version_id=other_version.id,
        )
    )

    with pytest.raises(IntegrityError, match="fk_test_batches_taxonomy_version_system"):
        await db_session.commit()
    await db_session.rollback()

    await db_session.execute(delete(System).where(System.id == other_system_id))
    await db_session.commit()


async def test_database_rejects_case_concept_from_another_taxonomy_version(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, document_id = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="version-one-only")
    v1 = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="test",
    )
    v2 = TaxonomyVersion(
        system_id=system_id,
        version=2,
        status="draft",
        manifest_hash="2" * 64,
        definition_hash="2" * 64,
        change_note="v2",
        created_by="test",
    )
    db_session.add_all([concept, v1, v2])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=v1.id,
            concept_id=concept.id,
            node_type="module",
            display_name="仅存在于 v1",
        )
    )
    batch = BatchModel(
        document_id=document_id,
        system_id=system_id,
        status="completed",
        taxonomy_version_id=v2.id,
    )
    db_session.add(batch)
    await db_session.flush()
    db_session.add(
        CaseModel(
            batch_id=batch.id,
            title="跨版本用例",
            preconditions=[],
            steps=[],
            expected_results=[],
            priority="P1",
            dimensions=[],
            provenance={},
            trust_level=1,
            taxonomy_version_id=v2.id,
            taxonomy_concept_id=concept.id,
        )
    )

    with pytest.raises(IntegrityError, match="fk_test_cases_taxonomy_node"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_related_concept_from_another_taxonomy_version(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, document_id = seeded_system
    target = TaxonomyConcept(system_id=system_id, stable_key="target-v1")
    related = TaxonomyConcept(system_id=system_id, stable_key="related-v2")
    v1 = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="test",
    )
    v2 = TaxonomyVersion(
        system_id=system_id,
        version=2,
        status="draft",
        manifest_hash="2" * 64,
        definition_hash="2" * 64,
        change_note="v2",
        created_by="test",
    )
    db_session.add_all([target, related, v1, v2])
    await db_session.flush()
    db_session.add_all(
        [
            TaxonomyNode(
                system_id=system_id,
                taxonomy_version_id=v1.id,
                concept_id=target.id,
                node_type="module",
                display_name="目标",
            ),
            TaxonomyNode(
                system_id=system_id,
                taxonomy_version_id=v2.id,
                concept_id=related.id,
                node_type="module",
                display_name="错误版本关联",
            ),
        ]
    )
    batch = BatchModel(
        document_id=document_id,
        system_id=system_id,
        status="completed",
        taxonomy_version_id=v1.id,
    )
    db_session.add(batch)
    await db_session.flush()
    case = CaseModel(
        batch_id=batch.id,
        title="关联能力跨版本",
        preconditions=[],
        steps=[],
        expected_results=[],
        priority="P1",
        dimensions=[],
        provenance={},
        trust_level=1,
        taxonomy_version_id=v1.id,
        taxonomy_concept_id=target.id,
    )
    db_session.add(case)
    await db_session.flush()
    db_session.add(
        _CaseRelatedTaxonomyConcept(
            case_id=case.id,
            taxonomy_version_id=v1.id,
            concept_id=related.id,
        )
    )

    with pytest.raises(IntegrityError, match="fk_case_related_taxonomy_node"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_active_taxonomy_content_mutation(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="immutable")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="immutable",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    node = TaxonomyNode(
        system_id=system_id,
        taxonomy_version_id=version.id,
        concept_id=concept.id,
        node_type="module",
        display_name="不可变节点",
    )
    db_session.add(node)
    await db_session.commit()

    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    await db_session.commit()
    version_id = version.id

    node.display_name = "静默篡改"
    with pytest.raises(DBAPIError, match="nodes of active/retired taxonomy are immutable"):
        await db_session.commit()
    await db_session.rollback()

    version = await db_session.get(TaxonomyVersion, version_id)
    assert version is not None
    version.manifest_hash = "2" * 64
    with pytest.raises(DBAPIError, match="taxonomy version identity/content is immutable"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_activating_version_older_than_activation_history(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    v1 = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="author",
    )
    v2 = TaxonomyVersion(
        system_id=system_id,
        version=2,
        status="draft",
        manifest_hash="2" * 64,
        definition_hash="2" * 64,
        change_note="v2",
        created_by="author",
    )
    db_session.add_all([v1, v2])
    await db_session.commit()
    v2.status = "active"
    v2.activated_by = "newer-reviewer"
    v2.activated_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(DBAPIError, match="taxonomy activation must move forward"):
        async with db_session.begin_nested():
            v2.status = "retired"
            await db_session.flush()
            v1.status = "active"
            v1.activated_by = "older-reviewer"
            v1.activated_at = datetime.now(timezone.utc)
            await db_session.flush()

    await db_session.refresh(v1)
    await db_session.refresh(v2)
    assert (v1.status, v2.status) == ("draft", "active")


@pytest.mark.parametrize("final_status", ["active", "retired"])
async def test_database_rejects_delete_of_frozen_version_and_node(
    db_session: AsyncSession,
    seeded_system,
    final_status: str,
) -> None:
    system_id, _ = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key=f"delete-guard-{final_status}")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="delete guard",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    node = TaxonomyNode(
        system_id=system_id,
        taxonomy_version_id=version.id,
        concept_id=concept.id,
        node_type="module",
        display_name="不可删除节点",
    )
    db_session.add(node)
    await db_session.flush()
    version.status = "active"
    version.activated_by = "reviewer"
    version.activated_at = datetime.now(timezone.utc)
    await db_session.flush()
    if final_status == "retired":
        version.status = "retired"
        await db_session.flush()

    with pytest.raises(DBAPIError, match="nodes of active/retired taxonomy are immutable"):
        async with db_session.begin_nested():
            await db_session.execute(delete(TaxonomyNode).where(TaxonomyNode.id == node.id))

    with pytest.raises(DBAPIError, match="active/retired taxonomy version cannot be deleted"):
        async with db_session.begin_nested():
            await db_session.execute(delete(TaxonomyVersion).where(TaxonomyVersion.id == version.id))


@pytest.mark.parametrize("final_status", ["approved", "rejected", "superseded"])
async def test_database_rejects_delete_of_reviewed_mapping_without_related_rows(
    db_session: AsyncSession,
    seeded_system,
    final_status: str,
) -> None:
    system_id, document_id = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key=f"mapping-delete-{final_status}")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="mapping delete guard",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="映射目标",
        )
    )
    await db_session.flush()
    mapping = RequirementTaxonomyMapping(
        system_id=system_id,
        document_id=document_id,
        document_content_hash="d" * 64,
        feature_fingerprint="f" * 64,
        scope="feature_default",
        selector=None,
        selector_hash=hashlib.sha256(b"{}").hexdigest(),
        concept_id=concept.id,
        mapping_method="manual",
        confidence=1,
        reason="人工审核",
        review_status="pending",
        reviewed_by=None,
        reviewed_at=None,
        reviewed_taxonomy_version_id=version.id,
    )
    db_session.add(mapping)
    await db_session.flush()
    mapping.reviewed_by = "reviewer"
    mapping.reviewed_at = datetime.now(timezone.utc)
    mapping.review_status = "rejected" if final_status == "rejected" else "approved"
    await db_session.flush()
    if final_status == "superseded":
        mapping.review_status = "superseded"
        await db_session.flush()

    with pytest.raises(DBAPIError, match="reviewed taxonomy mapping cannot be deleted"):
        async with db_session.begin_nested():
            await db_session.execute(
                delete(RequirementTaxonomyMapping).where(RequirementTaxonomyMapping.id == mapping.id)
            )


async def test_database_requires_reviewer_metadata_for_rejected_mapping(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, document_id = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="rejected-review-metadata")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="review metadata",
        created_by="author",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="审核元数据",
        )
    )
    await db_session.commit()

    db_session.add(
        RequirementTaxonomyMapping(
            system_id=system_id,
            document_id=document_id,
            document_content_hash="d" * 64,
            feature_fingerprint="f" * 64,
            scope="feature_default",
            selector=None,
            selector_hash=hashlib.sha256(b"{}").hexdigest(),
            concept_id=concept.id,
            mapping_method="manual",
            confidence=1,
            reason="拒绝时也必须记录审核人",
            review_status="rejected",
            reviewed_by=None,
            reviewed_at=None,
            reviewed_taxonomy_version_id=version.id,
        )
    )
    with pytest.raises(IntegrityError, match="ck_req_tax_mapping_review_metadata"):
        await db_session.commit()
    await db_session.rollback()


async def test_database_rejects_selector_scope_mismatch(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, document_id = seeded_system
    concept = TaxonomyConcept(system_id=system_id, stable_key="module")
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash="1" * 64,
        change_note="v1",
        created_by="test",
    )
    db_session.add_all([concept, version])
    await db_session.flush()
    db_session.add(
        TaxonomyNode(
            system_id=system_id,
            taxonomy_version_id=version.id,
            concept_id=concept.id,
            node_type="module",
            display_name="模块",
        )
    )
    await db_session.flush()
    db_session.add(
        RequirementTaxonomyMapping(
            system_id=system_id,
            document_id=document_id,
            document_content_hash="d" * 64,
            feature_fingerprint="f" * 64,
            scope="feature_default",
            selector={"rule_id": "R-001"},
            selector_hash="s" * 64,
            concept_id=concept.id,
            mapping_method="manual",
            confidence=1,
            reason="invalid selector shape",
            review_status="approved",
            reviewed_by="test",
            reviewed_at=datetime.now(timezone.utc),
            reviewed_taxonomy_version_id=version.id,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
