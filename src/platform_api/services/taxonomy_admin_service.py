"""Taxonomy manifest 导入与版本激活的事务服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
)
from src.platform_api.repositories.taxonomy_repo import TaxonomyRepository
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest, TaxonomyMappingManifest
from src.testcase_generator.services.taxonomy_manifest import manifest_hash


class TaxonomyAdminError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class TaxonomyImportResult:
    applied: bool
    idempotent: bool
    version_id: UUID | None
    manifest_hash: str
    concepts_to_create: int
    nodes_to_create: int
    mappings_to_create: int


@dataclass(frozen=True)
class TaxonomyActivationResult:
    applied: bool
    idempotent: bool
    version_id: UUID
    version: int
    retiring_version_id: UUID | None


@dataclass(frozen=True)
class _MappingPlanItem:
    mapping: TaxonomyMappingManifest
    existing: RequirementTaxonomyMapping | None
    create: bool


class TaxonomyAdminService:
    """所有写操作都由方法内事务提交；异常时整笔回滚。"""

    def __init__(self, session: AsyncSession, *, repository: TaxonomyRepository | None = None):
        self.session = session
        self.repository = repository or TaxonomyRepository(session)

    async def import_manifest(
        self,
        manifest: TaxonomyManifest,
        *,
        apply: bool = False,
        actor: str | None = None,
    ) -> TaxonomyImportResult:
        actor = self._validated_actor(actor or manifest.created_by)
        self._require_clean_transaction()
        async with self.session.begin():
            return await self._import_manifest(manifest, apply=apply, actor=actor)

    async def activate(
        self,
        *,
        system_id: UUID,
        version: int,
        actor: str,
        apply: bool = False,
    ) -> TaxonomyActivationResult:
        actor = self._validated_actor(actor)
        self._require_clean_transaction()
        async with self.session.begin():
            versions = await self.repository.list_versions(system_id, for_update=apply)
            target = next((item for item in versions if item.version == version), None)
            if target is None:
                raise TaxonomyAdminError("taxonomy_version_not_found", f"version={version}")
            if target.status == "active":
                return TaxonomyActivationResult(
                    applied=False,
                    idempotent=True,
                    version_id=target.id,
                    version=target.version,
                    retiring_version_id=None,
                )
            if target.status != "draft":
                raise TaxonomyAdminError("retired_version_cannot_activate", f"version={version}")

            current = next((item for item in versions if item.status == "active"), None)
            result = TaxonomyActivationResult(
                applied=apply,
                idempotent=False,
                version_id=target.id,
                version=target.version,
                retiring_version_id=current.id if current else None,
            )
            if not apply:
                return result

            if current is not None:
                current.status = "retired"
                await self.session.flush()
            target.status = "active"
            target.activated_by = actor
            target.activated_at = datetime.now(timezone.utc)
            await self.session.flush()
            return result

    async def _import_manifest(
        self,
        manifest: TaxonomyManifest,
        *,
        apply: bool,
        actor: str,
    ) -> TaxonomyImportResult:
        digest = manifest_hash(manifest)
        await self._validate_sources(manifest)
        existing_version = await self.repository.get_version(
            manifest.system_id,
            manifest.version,
            for_update=apply,
        )
        if existing_version is not None:
            if existing_version.manifest_hash != digest:
                raise TaxonomyAdminError(
                    "version_manifest_conflict",
                    f"version={manifest.version} 已绑定其他 manifest hash",
                )
            return TaxonomyImportResult(
                applied=False,
                idempotent=True,
                version_id=existing_version.id,
                manifest_hash=digest,
                concepts_to_create=0,
                nodes_to_create=0,
                mappings_to_create=0,
            )

        stable_keys = {node.stable_key for node in manifest.nodes}
        concepts = await self.repository.get_concepts(manifest.system_id, stable_keys)
        mapping_plan = await self._mapping_plan(manifest)
        result = TaxonomyImportResult(
            applied=apply,
            idempotent=False,
            version_id=None,
            manifest_hash=digest,
            concepts_to_create=len(stable_keys - concepts.keys()),
            nodes_to_create=len(manifest.nodes),
            mappings_to_create=sum(1 for item in mapping_plan if item.create),
        )
        if not apply:
            return result

        new_concepts = [
            TaxonomyConcept(system_id=manifest.system_id, stable_key=stable_key)
            for stable_key in sorted(stable_keys - concepts.keys())
        ]
        await self.repository.add_concepts(new_concepts)
        concepts.update({concept.stable_key: concept for concept in new_concepts})

        version = TaxonomyVersion(
            system_id=manifest.system_id,
            version=manifest.version,
            status="draft",
            manifest_hash=digest,
            change_note=manifest.change_note,
            created_by=actor,
        )
        await self.repository.add_version(version)
        await self.repository.add_nodes(
            TaxonomyNode(
                system_id=manifest.system_id,
                taxonomy_version_id=version.id,
                concept_id=concepts[node.stable_key].id,
                parent_concept_id=(concepts[node.parent_stable_key].id if node.parent_stable_key else None),
                node_type=node.node_type,
                display_name=node.display_name,
                aliases=node.aliases,
                sort_order=node.sort_order,
                node_status=node.node_status,
                replacement_concept_id=(
                    concepts[node.replacement_stable_key].id if node.replacement_stable_key else None
                ),
            )
            for node in manifest.nodes
        )

        mappings: list[RequirementTaxonomyMapping] = []
        for item in mapping_plan:
            mapping = item.mapping
            existing = item.existing
            target = concepts[mapping.target_stable_key]
            if not item.create:
                continue
            if existing is not None:
                existing.review_status = "superseded"
            mappings.append(
                RequirementTaxonomyMapping(
                    id=uuid.uuid4(),
                    system_id=manifest.system_id,
                    document_id=mapping.document_id,
                    document_content_hash=mapping.document_content_hash,
                    feature_fingerprint=mapping.feature_fingerprint,
                    scope=mapping.scope,
                    selector=mapping.selector.model_dump(mode="json", exclude_none=True) if mapping.selector else None,
                    selector_hash=mapping.selector_hash,
                    concept_id=target.id,
                    related_concept_ids=[str(concepts[key].id) for key in mapping.related_stable_keys],
                    mapping_method=mapping.mapping_method,
                    confidence=mapping.confidence,
                    reason=mapping.reason,
                    review_status=mapping.review_status,
                    reviewed_by=mapping.reviewed_by,
                    reviewed_at=mapping.reviewed_at,
                    reviewed_taxonomy_version_id=version.id,
                    supersedes_mapping_id=mapping.supersedes_mapping_id,
                )
            )
        await self.repository.add_mappings(mappings)
        return TaxonomyImportResult(**{**result.__dict__, "version_id": version.id})

    async def _validate_sources(self, manifest: TaxonomyManifest) -> None:
        if await self.repository.get_system(manifest.system_id) is None:
            raise TaxonomyAdminError("system_not_found", str(manifest.system_id))
        documents = await self.repository.get_documents({mapping.document_id for mapping in manifest.mappings})
        for mapping in manifest.mappings:
            document = documents.get(mapping.document_id)
            if document is None:
                raise TaxonomyAdminError("mapping_document_not_found", str(mapping.document_id))
            if document.system_id != manifest.system_id:
                raise TaxonomyAdminError("mapping_document_cross_system", str(mapping.document_id))
            if document.content_hash != mapping.document_content_hash:
                raise TaxonomyAdminError("mapping_document_hash_mismatch", str(mapping.document_id))

    async def _mapping_plan(
        self,
        manifest: TaxonomyManifest,
    ) -> list[_MappingPlanItem]:
        plan: list[_MappingPlanItem] = []
        for mapping in manifest.mappings:
            existing = None
            create = True
            if mapping.review_status == "approved":
                existing = await self.repository.get_current_approved_mapping(
                    system_id=manifest.system_id,
                    document_id=mapping.document_id,
                    document_content_hash=mapping.document_content_hash,
                    feature_fingerprint=mapping.feature_fingerprint,
                    scope=mapping.scope,
                    selector_hash=mapping.selector_hash,
                )
                if existing is not None:
                    existing_target = await self.repository.get_concept(existing.concept_id)
                    target_changed = existing_target is None or existing_target.stable_key != mapping.target_stable_key
                    if mapping.supersedes_mapping_id is None and target_changed:
                        raise TaxonomyAdminError(
                            "approved_mapping_supersede_required",
                            f"mapping={mapping.identity}",
                        )
                    if mapping.supersedes_mapping_id is not None and mapping.supersedes_mapping_id != existing.id:
                        raise TaxonomyAdminError(
                            "approved_mapping_supersede_mismatch",
                            f"mapping={mapping.identity}",
                        )
                    create = mapping.supersedes_mapping_id is not None
                elif mapping.supersedes_mapping_id is not None:
                    raise TaxonomyAdminError(
                        "approved_mapping_to_supersede_not_current",
                        f"mapping={mapping.identity}",
                    )
            plan.append(_MappingPlanItem(mapping=mapping, existing=existing, create=create))
        return plan

    def _require_clean_transaction(self) -> None:
        if self.session.in_transaction():
            raise TaxonomyAdminError(
                "transaction_already_active",
                "TaxonomyAdminService 必须使用未开启事务的 session",
            )

    @staticmethod
    def _validated_actor(actor: str) -> str:
        normalized = actor.strip()
        if not normalized:
            raise TaxonomyAdminError("actor_required", "操作者不能为空")
        if len(normalized) > 100:
            raise TaxonomyAdminError("actor_too_long", "操作者长度不能超过 100")
        return normalized
