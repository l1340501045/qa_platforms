from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError
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
from src.platform_api.models.testcase import TestBatch as BatchModel
from src.platform_api.models.testcase import TestCase as CaseModel
from src.platform_api.models.testcase import TestPoint as PointModel
from tests.platform_api.conftest import requires_db

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
    await db_session.execute(
        delete(RequirementTaxonomyMapping).where(RequirementTaxonomyMapping.system_id == system_id)
    )
    await db_session.execute(delete(TaxonomyNode).where(TaxonomyNode.system_id == system_id))
    await db_session.execute(delete(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id))
    await db_session.execute(delete(TaxonomyConcept).where(TaxonomyConcept.system_id == system_id))
    await db_session.execute(delete(Document).where(Document.id == document_id))
    await db_session.execute(delete(System).where(System.id == system_id))
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
        assert columns[table]["taxonomy_concept_id"]["nullable"] is True
        assert columns[table]["related_taxonomy_concept_ids"]["nullable"] is True
        assert columns[table]["taxonomy_resolution"]["nullable"] is True

    assert hasattr(BatchModel, "taxonomy_version_id")
    assert hasattr(PointModel, "taxonomy_concept_id")
    assert hasattr(CaseModel, "taxonomy_concept_id")


async def test_database_enforces_one_active_version_per_system(
    db_session: AsyncSession,
    seeded_system,
) -> None:
    system_id, _ = seeded_system
    db_session.add(
        TaxonomyVersion(
            id=uuid.uuid4(),
            system_id=system_id,
            version=1,
            status="active",
            manifest_hash="1" * 64,
            change_note="v1",
            created_by="test",
        )
    )
    await db_session.commit()

    db_session.add(
        TaxonomyVersion(
            id=uuid.uuid4(),
            system_id=system_id,
            version=2,
            status="active",
            manifest_hash="2" * 64,
            change_note="v2",
            created_by="test",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    await db_session.execute(delete(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id))
    await db_session.commit()


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
        change_note="v1",
        created_by="test",
    )
    v2 = TaxonomyVersion(
        system_id=system_id,
        version=2,
        status="draft",
        manifest_hash="2" * 64,
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
        change_note="v1",
        created_by="test",
    )
    db_session.add_all([concept, version])
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
            related_concept_ids=[],
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
