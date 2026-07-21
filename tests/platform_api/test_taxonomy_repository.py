from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
)
from src.platform_api.services.taxonomy_admin_service import TaxonomyAdminError, TaxonomyAdminService
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest
from src.testcase_generator.services.taxonomy_manifest import taxonomy_node_definition_hash
from tests.platform_api.conftest import requires_db, set_taxonomy_immutability_triggers

pytestmark = requires_db


@pytest.fixture
async def db_session() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def taxonomy_source(db_session: AsyncSession):
    system_id = uuid.uuid4()
    document_id = uuid.uuid4()
    content_hash = hashlib.sha256(str(document_id).encode()).hexdigest()
    db_session.add(System(id=system_id, name=f"taxonomy-admin-{uuid.uuid4()}"))
    await db_session.flush()
    db_session.add(
        Document(
            id=document_id,
            system_id=system_id,
            title="taxonomy admin test",
            doc_type="prd",
            content="# test",
            storage_path=f"test/{document_id}.md",
            content_hash=content_hash,
        )
    )
    await db_session.commit()
    yield system_id, document_id, content_hash

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


def _manifest(
    *,
    system_id: uuid.UUID,
    document_id: uuid.UUID,
    content_hash: str,
    version: int = 1,
    change_note: str = "v1",
) -> TaxonomyManifest:
    return TaxonomyManifest.model_validate(
        {
            "schema_version": 1,
            "system_id": str(system_id),
            "version": version,
            "change_note": change_note,
            "created_by": "test",
            "nodes": [
                {
                    "stable_key": "asset-center",
                    "node_type": "module",
                    "display_name": "素材中心",
                },
                {
                    "stable_key": "asset-center.filter",
                    "node_type": "capability",
                    "display_name": "筛选与排序",
                    "parent_stable_key": "asset-center",
                },
            ],
            "mappings": [
                {
                    "document_id": str(document_id),
                    "document_content_hash": content_hash,
                    "feature_fingerprint": "f" * 64,
                    "scope": "feature_default",
                    "target_stable_key": "asset-center.filter",
                    "mapping_method": "manual",
                    "confidence": 1,
                    "reason": "人工校准",
                    "review_status": "approved",
                    "reviewed_by": "mapping-reviewer",
                    "reviewed_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
                }
            ],
        }
    )


def _v2_manifest(
    *,
    system_id: uuid.UUID,
    document_id: uuid.UUID,
    content_hash: str,
) -> TaxonomyManifest:
    payload = _manifest(
        system_id=system_id,
        document_id=document_id,
        content_hash=content_hash,
    ).model_dump(mode="json")
    payload["schema_version"] = 2
    payload["nodes"][0].update(
        {
            "definition": "管理系统内可复用的素材资产。",
            "scope_note": "包含素材管理，不包含广告任务执行。",
        }
    )
    payload["nodes"][1].update(
        {
            "definition": "按条件筛选素材并调整结果顺序。",
            "scope_note": "包含筛选与排序，不包含上传。",
            "in_scope_examples": [
                {
                    "text": "素材列表支持按创建时间排序。",
                    "document_content_hash": content_hash,
                    "requirement_unit_id": f"ru_{'1' * 64}",
                }
            ],
            "out_of_scope_examples": [],
        }
    )
    return TaxonomyManifest.model_validate(payload)


async def test_import_dry_run_writes_nothing(db_session: AsyncSession, taxonomy_source) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)

    result = await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=False,
    )

    assert result.applied is False
    count = await db_session.scalar(
        select(func.count()).select_from(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id)
    )
    assert count == 0
    await db_session.rollback()


async def test_import_is_idempotent_for_same_manifest(db_session: AsyncSession, taxonomy_source) -> None:
    system_id, document_id, content_hash = taxonomy_source
    manifest = _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash)
    service = TaxonomyAdminService(db_session)

    first = await service.import_manifest(manifest, apply=True)
    second = await service.import_manifest(manifest, apply=True)

    assert first.applied is True
    assert first.idempotent is False
    assert second.applied is False
    assert second.idempotent is True
    assert first.version_id == second.version_id
    assert await db_session.scalar(
        select(func.count()).select_from(TaxonomyConcept).where(TaxonomyConcept.system_id == system_id)
    ) == len(manifest.nodes)
    await db_session.rollback()


async def test_import_v2_persists_schema_and_node_semantics(db_session: AsyncSession, taxonomy_source) -> None:
    system_id, document_id, content_hash = taxonomy_source
    manifest = _v2_manifest(system_id=system_id, document_id=document_id, content_hash=content_hash)
    service = TaxonomyAdminService(db_session)

    result = await service.import_manifest(manifest, apply=True)
    version = await db_session.get(TaxonomyVersion, result.version_id)
    nodes = list(
        (
            await db_session.execute(
                select(TaxonomyNode)
                .where(TaxonomyNode.taxonomy_version_id == result.version_id)
                .order_by(TaxonomyNode.display_name)
            )
        )
        .scalars()
        .all()
    )

    assert version is not None
    assert version.schema_version == 2
    capability = next(node for node in nodes if node.node_type == "capability")
    assert capability.definition == "按条件筛选素材并调整结果顺序。"
    assert capability.scope_note == "包含筛选与排序，不包含上传。"
    assert capability.in_scope_examples[0]["requirement_unit_id"] == f"ru_{'1' * 64}"
    assert capability.out_of_scope_examples == []
    await db_session.rollback()


async def test_activate_revalidates_v2_semantics_before_database_transition(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, _, _ = taxonomy_source
    concept = TaxonomyConcept(system_id=system_id, stable_key="missing-evidence")
    payload = {
        "stable_key": "missing-evidence",
        "node_type": "capability",
        "display_name": "缺少证据",
        "aliases": [],
        "sort_order": 0,
        "node_status": "active",
        "definition": "缺少正向证据的能力定义。",
        "scope_note": "用于验证激活门禁。",
    }
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash=taxonomy_node_definition_hash([payload]),
        change_note="malformed v2 draft",
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
            display_name="缺少证据",
            definition="缺少正向证据的能力定义。",
            scope_note="用于验证激活门禁。",
        )
    )
    await db_session.commit()

    with pytest.raises(TaxonomyAdminError, match="v2_active_capability_in_scope_evidence_required"):
        await TaxonomyAdminService(db_session).activate(
            system_id=system_id,
            version=1,
            actor="reviewer",
            apply=False,
        )


async def test_activate_revalidates_v2_example_shape_before_database_transition(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, _, _ = taxonomy_source
    concept = TaxonomyConcept(system_id=system_id, stable_key="invalid-example")
    malformed_example = {
        "text": "来源标识格式无效",
        "document_content_hash": "invalid",
        "requirement_unit_id": "invalid",
    }
    payload = {
        "stable_key": "invalid-example",
        "node_type": "capability",
        "display_name": "示例结构无效",
        "aliases": [],
        "sort_order": 0,
        "node_status": "active",
        "definition": "包含无效证据结构的能力。",
        "scope_note": "用于验证强类型重放。",
        "in_scope_examples": [malformed_example],
    }
    version = TaxonomyVersion(
        system_id=system_id,
        version=1,
        schema_version=2,
        status="draft",
        manifest_hash="1" * 64,
        definition_hash=taxonomy_node_definition_hash([payload]),
        change_note="malformed example",
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
            display_name="示例结构无效",
            definition="包含无效证据结构的能力。",
            scope_note="用于验证强类型重放。",
            in_scope_examples=[malformed_example],
        )
    )
    await db_session.commit()

    with pytest.raises(TaxonomyAdminError, match="v2_node_semantics_invalid"):
        await TaxonomyAdminService(db_session).activate(
            system_id=system_id,
            version=1,
            actor="reviewer",
            apply=False,
        )


async def test_import_rejects_same_version_with_different_hash(db_session: AsyncSession, taxonomy_source) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=True,
    )
    changed = _manifest(
        system_id=system_id,
        document_id=document_id,
        content_hash=content_hash,
        change_note="changed",
    )

    with pytest.raises(TaxonomyAdminError, match="version_manifest_conflict"):
        await service.import_manifest(changed, apply=True)


async def test_activate_retires_previous_version_atomically(db_session: AsyncSession, taxonomy_source) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=True,
    )
    await service.activate(system_id=system_id, version=1, actor="first-reviewer", apply=True)
    await service.import_manifest(
        _manifest(
            system_id=system_id,
            document_id=document_id,
            content_hash=content_hash,
            version=2,
            change_note="v2",
        ),
        apply=True,
    )

    result = await service.activate(system_id=system_id, version=2, actor="second-reviewer", apply=True)
    rows = list(
        (
            await db_session.execute(
                select(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id).order_by(TaxonomyVersion.version)
            )
        )
        .scalars()
        .all()
    )

    assert result.applied is True
    assert [(row.version, row.status) for row in rows] == [(1, "retired"), (2, "active")]
    assert rows[1].activated_by == "second-reviewer"
    await db_session.rollback()


async def test_activate_rejects_draft_older_than_activation_history(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=True,
    )
    await service.import_manifest(
        _manifest(
            system_id=system_id,
            document_id=document_id,
            content_hash=content_hash,
            version=2,
            change_note="v2",
        ),
        apply=True,
    )
    await service.activate(system_id=system_id, version=2, actor="newer-reviewer", apply=True)
    newer = await db_session.scalar(
        select(TaxonomyVersion).where(
            TaxonomyVersion.system_id == system_id,
            TaxonomyVersion.version == 2,
        )
    )
    assert newer is not None
    newer.status = "retired"
    await db_session.commit()

    with pytest.raises(TaxonomyAdminError, match="taxonomy_activation_version_not_newer"):
        await service.activate(system_id=system_id, version=1, actor="older-reviewer", apply=True)

    rows = list(
        (
            await db_session.execute(
                select(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id).order_by(TaxonomyVersion.version)
            )
        )
        .scalars()
        .all()
    )
    assert [(row.version, row.status) for row in rows] == [(1, "draft"), (2, "retired")]


async def test_activate_rejects_manifest_creator_as_reviewer(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=True,
    )

    with pytest.raises(TaxonomyAdminError, match="taxonomy_activation_self_approval_forbidden"):
        await service.activate(system_id=system_id, version=1, actor="TEST", apply=True)


async def test_changed_approved_mapping_requires_explicit_supersede(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=True,
    )
    current = (
        await db_session.execute(
            select(RequirementTaxonomyMapping).where(
                RequirementTaxonomyMapping.system_id == system_id,
                RequirementTaxonomyMapping.review_status == "approved",
            )
        )
    ).scalar_one()
    current_id = current.id
    await db_session.rollback()

    changed_data = _manifest(
        system_id=system_id,
        document_id=document_id,
        content_hash=content_hash,
        version=2,
        change_note="mapping changed",
    ).model_dump(mode="json")
    changed_data["mappings"][0]["target_stable_key"] = "asset-center"
    changed = TaxonomyManifest.model_validate(changed_data)
    with pytest.raises(TaxonomyAdminError, match="approved_mapping_supersede_required"):
        await service.import_manifest(changed, apply=True)

    changed_data["mappings"][0]["supersedes_mapping_id"] = str(current_id)
    corrected = TaxonomyManifest.model_validate(changed_data)
    result = await service.import_manifest(corrected, apply=True)
    rows = list(
        (
            await db_session.execute(
                select(RequirementTaxonomyMapping)
                .where(RequirementTaxonomyMapping.system_id == system_id)
                .order_by(RequirementTaxonomyMapping.created_at)
            )
        )
        .scalars()
        .all()
    )

    assert result.mappings_to_create == 1
    assert len(rows) == 2
    old = next(row for row in rows if row.id == current_id)
    new = next(row for row in rows if row.id != current_id)
    assert old.review_status == "superseded"
    assert new.review_status == "approved"
    assert new.supersedes_mapping_id == current_id
    await db_session.rollback()


async def test_import_rejects_mapping_supersede_from_older_taxonomy_version(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(
            system_id=system_id,
            document_id=document_id,
            content_hash=content_hash,
            version=2,
            change_note="newer mapping",
        ),
        apply=True,
    )
    current_id = await db_session.scalar(
        select(RequirementTaxonomyMapping.id).where(
            RequirementTaxonomyMapping.system_id == system_id,
            RequirementTaxonomyMapping.review_status == "approved",
        )
    )
    assert current_id is not None
    await db_session.rollback()

    older_data = _manifest(
        system_id=system_id,
        document_id=document_id,
        content_hash=content_hash,
        version=1,
        change_note="older mapping must not supersede",
    ).model_dump(mode="json")
    older_data["mappings"][0]["target_stable_key"] = "asset-center"
    older_data["mappings"][0]["supersedes_mapping_id"] = str(current_id)

    with pytest.raises(TaxonomyAdminError, match="approved_mapping_version_not_newer"):
        await service.import_manifest(TaxonomyManifest.model_validate(older_data), apply=True)

    await db_session.rollback()
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(TaxonomyVersion)
            .where(
                TaxonomyVersion.system_id == system_id,
                TaxonomyVersion.version == 1,
            )
        )
        == 0
    )


async def test_unchanged_approved_mapping_is_reused_across_taxonomy_versions(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    system_id, document_id, content_hash = taxonomy_source
    service = TaxonomyAdminService(db_session)
    await service.import_manifest(
        _manifest(system_id=system_id, document_id=document_id, content_hash=content_hash),
        apply=True,
    )

    result = await service.import_manifest(
        _manifest(
            system_id=system_id,
            document_id=document_id,
            content_hash=content_hash,
            version=2,
            change_note="v2 same mapping",
        ),
        apply=True,
    )
    mapping_count = await db_session.scalar(
        select(func.count())
        .select_from(RequirementTaxonomyMapping)
        .where(RequirementTaxonomyMapping.system_id == system_id)
    )

    assert result.mappings_to_create == 0
    assert mapping_count == 1
    await db_session.rollback()


async def test_import_rejects_mapping_document_from_another_system(
    db_session: AsyncSession,
    taxonomy_source,
) -> None:
    _, document_id, content_hash = taxonomy_source
    other_system_id = uuid.uuid4()
    db_session.add(System(id=other_system_id, name=f"taxonomy-other-{uuid.uuid4()}"))
    await db_session.commit()
    service = TaxonomyAdminService(db_session)

    with pytest.raises(TaxonomyAdminError, match="mapping_document_cross_system"):
        await service.import_manifest(
            _manifest(
                system_id=other_system_id,
                document_id=document_id,
                content_hash=content_hash,
            ),
            apply=True,
        )

    await db_session.execute(delete(System).where(System.id == other_system_id))
    await db_session.commit()
