"""Taxonomy manifest 导入与版本激活的事务服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    RequirementTaxonomyMappingRelatedConcept,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
)
from src.platform_api.repositories.taxonomy_repo import TaxonomyRepository
from src.testcase_generator.schemas.taxonomy import (
    TaxonomyManifest,
    TaxonomyMappingManifest,
    TaxonomyNodeManifest,
)
from src.testcase_generator.services.taxonomy_manifest import (
    manifest_hash,
    taxonomy_definition_hash,
    taxonomy_node_definition_hash,
)


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
    action: Literal["create", "reuse", "supersede"]


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
        if actor.casefold() != manifest.created_by.casefold():
            raise TaxonomyAdminError("manifest_creator_actor_mismatch", "manifest.created_by 必须等于导入操作者")
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
            latest_activated = max(
                (item for item in versions if item.status in {"active", "retired"}),
                key=lambda item: item.version,
                default=None,
            )
            if latest_activated is not None and target.version <= latest_activated.version:
                raise TaxonomyAdminError(
                    "taxonomy_activation_version_not_newer",
                    f"target version={target.version} 必须大于 activation history version={latest_activated.version}",
                )
            if target.created_by.casefold() == actor.casefold():
                raise TaxonomyAdminError(
                    "taxonomy_activation_self_approval_forbidden",
                    "taxonomy version 创建者不能激活自己导入的版本",
                )
            await self._validate_stored_definition(target, for_update=apply)

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
            await self._validate_stored_definition(existing_version, for_update=apply)
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
        mapping_plan = await self._mapping_plan(manifest, for_update=apply)
        result = TaxonomyImportResult(
            applied=apply,
            idempotent=False,
            version_id=None,
            manifest_hash=digest,
            concepts_to_create=len(stable_keys - concepts.keys()),
            nodes_to_create=len(manifest.nodes),
            mappings_to_create=sum(1 for item in mapping_plan if item.action != "reuse"),
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
            schema_version=manifest.schema_version,
            status="draft",
            manifest_hash=digest,
            definition_hash=taxonomy_definition_hash(manifest),
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
                definition=node.definition,
                scope_note=node.scope_note,
                in_scope_examples=[example.model_dump(mode="json") for example in (node.in_scope_examples or [])],
                out_of_scope_examples=[
                    example.model_dump(mode="json") for example in (node.out_of_scope_examples or [])
                ],
            )
            for node in manifest.nodes
        )

        mappings: list[tuple[RequirementTaxonomyMapping, TaxonomyMappingManifest, _MappingPlanItem]] = []
        for item in mapping_plan:
            mapping = item.mapping
            target = concepts[mapping.target_stable_key]
            if item.action == "reuse":
                continue
            stored_mapping = RequirementTaxonomyMapping(
                id=uuid.uuid4(),
                system_id=manifest.system_id,
                document_id=mapping.document_id,
                document_content_hash=mapping.document_content_hash,
                feature_fingerprint=mapping.feature_fingerprint,
                scope=mapping.scope,
                selector=mapping.selector.model_dump(mode="json", exclude_none=True) if mapping.selector else None,
                selector_hash=mapping.selector_hash,
                concept_id=target.id,
                mapping_method=mapping.mapping_method,
                confidence=mapping.confidence,
                reason=mapping.reason,
                review_status="pending",
                reviewed_by=None,
                reviewed_at=None,
                reviewed_taxonomy_version_id=version.id,
                supersedes_mapping_id=None,
            )
            mappings.append((stored_mapping, mapping, item))
        await self.repository.add_mappings(stored for stored, _, _ in mappings)
        await self.repository.add_mapping_related_concepts(
            RequirementTaxonomyMappingRelatedConcept(
                mapping_id=stored.id,
                taxonomy_version_id=version.id,
                concept_id=concepts[related_key].id,
            )
            for stored, mapping, _ in mappings
            for related_key in mapping.related_stable_keys
        )
        for _, _, item in mappings:
            if item.action == "supersede" and item.existing is not None:
                item.existing.review_status = "superseded"
        await self.session.flush()
        for stored, mapping, item in mappings:
            stored.review_status = mapping.review_status
            stored.reviewed_by = mapping.reviewed_by
            stored.reviewed_at = mapping.reviewed_at
            stored.supersedes_mapping_id = (
                item.existing.id if item.action == "supersede" and item.existing is not None else None
            )
        await self.session.flush()
        return TaxonomyImportResult(**{**result.__dict__, "version_id": version.id})

    async def _validate_stored_definition(
        self,
        version: TaxonomyVersion,
        *,
        for_update: bool,
    ) -> None:
        stored_nodes = await self.repository.list_nodes(version.id, for_update=for_update)
        key_by_concept = {stored.concept.id: stored.concept.stable_key for stored in stored_nodes}
        payloads: list[dict[str, Any]] = []
        for stored in stored_nodes:
            node = stored.node
            parent_key = key_by_concept.get(node.parent_concept_id) if node.parent_concept_id else None
            replacement_key = key_by_concept.get(node.replacement_concept_id) if node.replacement_concept_id else None
            if node.parent_concept_id and parent_key is None:
                raise TaxonomyAdminError("taxonomy_definition_parent_missing", str(node.parent_concept_id))
            if node.replacement_concept_id and replacement_key is None:
                raise TaxonomyAdminError(
                    "taxonomy_definition_replacement_missing",
                    str(node.replacement_concept_id),
                )
            payload = {
                "stable_key": stored.concept.stable_key,
                "node_type": node.node_type,
                "display_name": node.display_name,
                "aliases": node.aliases,
                "sort_order": node.sort_order,
                "node_status": node.node_status,
            }
            if parent_key is not None:
                payload["parent_stable_key"] = parent_key
            if replacement_key is not None:
                payload["replacement_stable_key"] = replacement_key
            if version.schema_version == 2:
                if node.definition is not None:
                    payload["definition"] = node.definition
                if node.scope_note is not None:
                    payload["scope_note"] = node.scope_note
                if node.in_scope_examples:
                    payload["in_scope_examples"] = node.in_scope_examples
                if node.out_of_scope_examples:
                    payload["out_of_scope_examples"] = node.out_of_scope_examples
            payloads.append(payload)
        manifest_nodes: list[TaxonomyNodeManifest] | None = None
        if version.schema_version == 2:
            try:
                manifest_nodes = [TaxonomyNodeManifest.model_validate(payload) for payload in payloads]
            except ValidationError as exc:
                raise TaxonomyAdminError(
                    "v2_node_semantics_invalid",
                    f"version={version.version} 的节点语义不符合 v2 契约",
                ) from exc
            self._validate_v2_semantics(manifest_nodes)
        if taxonomy_node_definition_hash(payloads) != version.definition_hash:
            raise TaxonomyAdminError(
                "taxonomy_definition_hash_mismatch",
                f"version={version.version} 的数据库节点已偏离导入 manifest",
            )

    @staticmethod
    def _validate_v2_semantics(nodes: list[TaxonomyNodeManifest]) -> None:
        if not nodes:
            raise TaxonomyAdminError("v2_taxonomy_node_required", "v2 taxonomy 至少需要一个节点")
        for node in nodes:
            stable_key = node.stable_key
            if not node.definition:
                raise TaxonomyAdminError(
                    "v2_node_definition_required",
                    f"stable_key={stable_key}",
                )
            if not node.scope_note:
                raise TaxonomyAdminError(
                    "v2_node_scope_note_required",
                    f"stable_key={stable_key}",
                )
            if node.node_type == "capability" and node.node_status == "active" and not node.in_scope_examples:
                raise TaxonomyAdminError(
                    "v2_active_capability_in_scope_evidence_required",
                    f"stable_key={stable_key}",
                )

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
        *,
        for_update: bool,
    ) -> list[_MappingPlanItem]:
        plan: list[_MappingPlanItem] = []
        versions_by_id = {
            version.id: version
            for version in await self.repository.list_versions(manifest.system_id, for_update=for_update)
        }
        for mapping in manifest.mappings:
            existing = None
            action: Literal["create", "reuse", "supersede"] = "create"
            if mapping.review_status == "approved":
                existing = await self.repository.get_current_approved_mapping(
                    system_id=manifest.system_id,
                    document_id=mapping.document_id,
                    document_content_hash=mapping.document_content_hash,
                    feature_fingerprint=mapping.feature_fingerprint,
                    scope=mapping.scope,
                    selector_hash=mapping.selector_hash,
                    for_update=for_update,
                )
                if existing is not None:
                    reviewed_version = versions_by_id.get(existing.reviewed_taxonomy_version_id)
                    if reviewed_version is None:
                        raise TaxonomyAdminError(
                            "approved_mapping_version_missing",
                            str(existing.id),
                        )
                    if manifest.version <= reviewed_version.version:
                        raise TaxonomyAdminError(
                            "approved_mapping_version_not_newer",
                            f"mapping={mapping.identity} existing_version={reviewed_version.version}",
                        )
                    equivalent = await self._mapping_payload_equivalent(existing, mapping)
                    if equivalent:
                        if mapping.supersedes_mapping_id is not None:
                            raise TaxonomyAdminError(
                                "approved_mapping_unnecessary_supersede",
                                f"mapping={mapping.identity}",
                            )
                        action = "reuse"
                    elif mapping.supersedes_mapping_id is None:
                        raise TaxonomyAdminError(
                            "approved_mapping_supersede_required",
                            f"mapping={mapping.identity}",
                        )
                    elif mapping.supersedes_mapping_id != existing.id:
                        raise TaxonomyAdminError(
                            "approved_mapping_supersede_mismatch",
                            f"mapping={mapping.identity}",
                        )
                    else:
                        action = "supersede"
                elif mapping.supersedes_mapping_id is not None:
                    raise TaxonomyAdminError(
                        "approved_mapping_to_supersede_not_current",
                        f"mapping={mapping.identity}",
                    )
            plan.append(_MappingPlanItem(mapping=mapping, existing=existing, action=action))
        return plan

    async def _mapping_payload_equivalent(
        self,
        existing: RequirementTaxonomyMapping,
        proposed: TaxonomyMappingManifest,
    ) -> bool:
        related_by_mapping = await self.repository.get_mapping_related_concepts({existing.id})
        related_ids = set(related_by_mapping.get(existing.id, ()))
        concepts = await self.repository.get_concepts_by_ids({existing.concept_id, *related_ids})
        target = concepts.get(existing.concept_id)
        related_keys = sorted(
            concept.stable_key for concept_id in related_ids if (concept := concepts.get(concept_id)) is not None
        )
        proposed_selector = proposed.selector.model_dump(mode="json", exclude_none=True) if proposed.selector else None
        return (
            target is not None
            and len(related_keys) == len(related_ids)
            and target.stable_key == proposed.target_stable_key
            and related_keys == sorted(proposed.related_stable_keys)
            and existing.selector == proposed_selector
            and existing.mapping_method == proposed.mapping_method
            and existing.confidence == proposed.confidence
            and existing.reason == proposed.reason
            and existing.reviewed_by == proposed.reviewed_by
            and existing.reviewed_at == proposed.reviewed_at
        )

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
