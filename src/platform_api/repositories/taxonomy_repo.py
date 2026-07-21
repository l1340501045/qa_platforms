"""业务 taxonomy 的数据访问层。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    RequirementTaxonomyMappingRelatedConcept,
    TaxonomyBackfillRun,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
    TestCaseRelatedTaxonomyConcept,
    TestPointRelatedTaxonomyConcept,
)
from src.platform_api.models.testcase import TestBatch, TestCase, TestPoint


@dataclass(frozen=True)
class StoredTaxonomyNode:
    node: TaxonomyNode
    concept: TaxonomyConcept


class TaxonomyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_system(self, system_id: UUID) -> System | None:
        return await self.session.get(System, system_id)

    async def get_documents(self, document_ids: set[UUID]) -> dict[UUID, Document]:
        if not document_ids:
            return {}
        rows = await self.session.execute(select(Document).where(Document.id.in_(document_ids)))
        return {row.id: row for row in rows.scalars().all()}

    async def get_document(self, document_id: UUID, *, for_update: bool = False) -> Document | None:
        stmt = select(Document).where(Document.id == document_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_batch(self, batch_id: UUID, *, for_update: bool = False) -> TestBatch | None:
        stmt = select(TestBatch).where(TestBatch.id == batch_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_batch_cases(self, batch_id: UUID, *, for_update: bool = False) -> list[TestCase]:
        stmt = select(TestCase).where(TestCase.batch_id == batch_id).order_by(TestCase.id)
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_batch_test_points(
        self,
        batch_id: UUID,
        test_point_ids: set[UUID],
        *,
        for_update: bool = False,
    ) -> list[TestPoint]:
        if not test_point_ids:
            return []
        stmt = (
            select(TestPoint)
            .where(TestPoint.batch_id == batch_id, TestPoint.id.in_(test_point_ids))
            .order_by(TestPoint.id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_version(
        self,
        system_id: UUID,
        version: int,
        *,
        for_update: bool = False,
    ) -> TaxonomyVersion | None:
        stmt = select(TaxonomyVersion).where(
            TaxonomyVersion.system_id == system_id,
            TaxonomyVersion.version == version,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_versions(self, system_id: UUID, *, for_update: bool = False) -> list[TaxonomyVersion]:
        stmt = select(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id).order_by(TaxonomyVersion.version)
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_concepts(self, system_id: UUID, stable_keys: set[str]) -> dict[str, TaxonomyConcept]:
        if not stable_keys:
            return {}
        rows = await self.session.execute(
            select(TaxonomyConcept).where(
                TaxonomyConcept.system_id == system_id,
                TaxonomyConcept.stable_key.in_(stable_keys),
            )
        )
        return {row.stable_key: row for row in rows.scalars().all()}

    async def get_concept(self, concept_id: UUID) -> TaxonomyConcept | None:
        return await self.session.get(TaxonomyConcept, concept_id)

    async def get_concepts_by_ids(self, concept_ids: set[UUID]) -> dict[UUID, TaxonomyConcept]:
        if not concept_ids:
            return {}
        rows = await self.session.execute(select(TaxonomyConcept).where(TaxonomyConcept.id.in_(concept_ids)))
        return {row.id: row for row in rows.scalars().all()}

    async def list_nodes(
        self,
        taxonomy_version_id: UUID,
        *,
        for_update: bool = False,
    ) -> list[StoredTaxonomyNode]:
        stmt = (
            select(TaxonomyNode, TaxonomyConcept)
            .join(TaxonomyConcept, TaxonomyConcept.id == TaxonomyNode.concept_id)
            .where(TaxonomyNode.taxonomy_version_id == taxonomy_version_id)
        )
        if for_update:
            stmt = stmt.with_for_update(of=TaxonomyNode)
        rows = await self.session.execute(stmt)
        return [StoredTaxonomyNode(node=node, concept=concept) for node, concept in rows.all()]

    async def get_mappings(
        self,
        mapping_ids: set[UUID],
        *,
        for_update: bool = False,
    ) -> dict[UUID, RequirementTaxonomyMapping]:
        if not mapping_ids:
            return {}
        stmt = select(RequirementTaxonomyMapping).where(RequirementTaxonomyMapping.id.in_(mapping_ids))
        if for_update:
            stmt = stmt.with_for_update()
        rows = await self.session.execute(stmt)
        return {row.id: row for row in rows.scalars().all()}

    async def list_document_mappings(
        self,
        *,
        system_id: UUID,
        document_id: UUID,
        document_content_hash: str,
        for_update: bool = False,
    ) -> list[RequirementTaxonomyMapping]:
        stmt = select(RequirementTaxonomyMapping).where(
            RequirementTaxonomyMapping.system_id == system_id,
            RequirementTaxonomyMapping.document_id == document_id,
            RequirementTaxonomyMapping.document_content_hash == document_content_hash,
            RequirementTaxonomyMapping.review_status.in_(("approved", "superseded")),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_mapping_related_concepts(
        self,
        mapping_ids: set[UUID],
        *,
        for_update: bool = False,
    ) -> dict[UUID, tuple[UUID, ...]]:
        if not mapping_ids:
            return {}
        stmt = select(RequirementTaxonomyMappingRelatedConcept).where(
            RequirementTaxonomyMappingRelatedConcept.mapping_id.in_(mapping_ids)
        )
        if for_update:
            stmt = stmt.with_for_update()
        rows = list((await self.session.execute(stmt)).scalars().all())
        grouped: dict[UUID, list[UUID]] = {}
        for row in rows:
            grouped.setdefault(row.mapping_id, []).append(row.concept_id)
        return {mapping_id: tuple(sorted(concept_ids)) for mapping_id, concept_ids in grouped.items()}

    async def get_case_related_concepts(
        self,
        case_ids: set[UUID],
        *,
        for_update: bool = False,
    ) -> dict[UUID, tuple[UUID, ...]]:
        if not case_ids:
            return {}
        stmt = select(TestCaseRelatedTaxonomyConcept).where(TestCaseRelatedTaxonomyConcept.case_id.in_(case_ids))
        if for_update:
            stmt = stmt.with_for_update()
        rows = list((await self.session.execute(stmt)).scalars().all())
        grouped: dict[UUID, list[UUID]] = {}
        for row in rows:
            grouped.setdefault(row.case_id, []).append(row.concept_id)
        return {case_id: tuple(sorted(concept_ids)) for case_id, concept_ids in grouped.items()}

    async def get_test_point_related_concepts(
        self,
        test_point_ids: set[UUID],
        *,
        for_update: bool = False,
    ) -> dict[UUID, tuple[UUID, ...]]:
        if not test_point_ids:
            return {}
        stmt = select(TestPointRelatedTaxonomyConcept).where(
            TestPointRelatedTaxonomyConcept.test_point_id.in_(test_point_ids)
        )
        if for_update:
            stmt = stmt.with_for_update()
        rows = list((await self.session.execute(stmt)).scalars().all())
        grouped: dict[UUID, list[UUID]] = {}
        for row in rows:
            grouped.setdefault(row.test_point_id, []).append(row.concept_id)
        return {test_point_id: tuple(sorted(concept_ids)) for test_point_id, concept_ids in grouped.items()}

    async def get_backfill_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> TaxonomyBackfillRun | None:
        stmt = select(TaxonomyBackfillRun).where(TaxonomyBackfillRun.id == run_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_current_approved_mapping(
        self,
        *,
        system_id: UUID,
        document_id: UUID,
        document_content_hash: str,
        feature_fingerprint: str,
        scope: str,
        selector_hash: str,
        for_update: bool = False,
    ) -> RequirementTaxonomyMapping | None:
        stmt = select(RequirementTaxonomyMapping).where(
            RequirementTaxonomyMapping.system_id == system_id,
            RequirementTaxonomyMapping.document_id == document_id,
            RequirementTaxonomyMapping.document_content_hash == document_content_hash,
            RequirementTaxonomyMapping.feature_fingerprint == feature_fingerprint,
            RequirementTaxonomyMapping.scope == scope,
            RequirementTaxonomyMapping.selector_hash == selector_hash,
            RequirementTaxonomyMapping.review_status == "approved",
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_concepts(self, concepts: Iterable[TaxonomyConcept]) -> None:
        self.session.add_all(list(concepts))
        await self.session.flush()

    async def add_version(self, version: TaxonomyVersion) -> None:
        self.session.add(version)
        await self.session.flush()

    async def add_nodes(self, nodes: Iterable[TaxonomyNode]) -> None:
        self.session.add_all(list(nodes))
        await self.session.flush()

    async def add_mappings(self, mappings: Iterable[RequirementTaxonomyMapping]) -> None:
        self.session.add_all(list(mappings))
        await self.session.flush()

    async def add_mapping_related_concepts(
        self,
        related: Iterable[RequirementTaxonomyMappingRelatedConcept],
    ) -> None:
        self.session.add_all(list(related))
        await self.session.flush()

    async def replace_case_related_concepts(
        self,
        case_ids: set[UUID],
        related: Iterable[TestCaseRelatedTaxonomyConcept],
    ) -> None:
        if case_ids:
            await self.session.execute(
                delete(TestCaseRelatedTaxonomyConcept).where(TestCaseRelatedTaxonomyConcept.case_id.in_(case_ids))
            )
        self.session.add_all(list(related))
        await self.session.flush()

    async def add_backfill_run(self, run: TaxonomyBackfillRun) -> None:
        self.session.add(run)
        await self.session.flush()
