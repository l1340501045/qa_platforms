"""业务 taxonomy 的数据访问层。"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
)


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

    async def get_current_approved_mapping(
        self,
        *,
        system_id: UUID,
        document_id: UUID,
        document_content_hash: str,
        feature_fingerprint: str,
        scope: str,
        selector_hash: str,
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
