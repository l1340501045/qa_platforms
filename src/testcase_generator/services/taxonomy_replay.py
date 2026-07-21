"""历史批次 taxonomy dry-run、apply 与精确 rollback。"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document
from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    TaxonomyBackfillRun,
    TaxonomyVersion,
    TestCaseRelatedTaxonomyConcept,
)
from src.platform_api.models.testcase import TestBatch, TestCase, TestPoint
from src.platform_api.repositories.taxonomy_repo import StoredTaxonomyNode, TaxonomyRepository
from src.testcase_generator.schemas.taxonomy import (
    TaxonomyAssignmentSet,
    TaxonomyCaseAssignment,
    TaxonomySelector,
    TaxonomySelectorFacts,
)
from src.testcase_generator.services.module_tree_classifier import classify_case_tree_coordinates
from src.testcase_generator.services.taxonomy_manifest import assignment_hash


class TaxonomyReplayError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ReplayCaseResult:
    case_id: UUID
    title: str
    priority: str
    bucket: str | None
    verdict: str | None
    is_main_candidate: bool
    source_refs: tuple[str, ...]
    legacy_classifier_module: str
    legacy_business_module: str
    legacy_branch_path: tuple[str, ...]
    legacy_confidence: str
    legacy_reason: str
    legacy_anomaly_category: str | None
    old_taxonomy_concept_id: UUID | None
    target_stable_key: str | None
    target_node_type: str | None
    related_stable_keys: tuple[str, ...]
    target_path: tuple[str, ...]
    assignment_source: str
    reason: str
    confidence: float | None
    unresolved_reason: str | None
    changed: bool


@dataclass(frozen=True)
class TaxonomyReplayResult:
    applied: bool
    run_id: UUID | None
    batch_id: UUID
    source_scope: str
    taxonomy_version_id: UUID
    taxonomy_version: int
    manifest_hash: str
    assignment_hash: str
    baseline_hash: str
    plan_hash: str
    case_set_hash: str
    provenance_hash: str
    applied_state_hash: str | None
    total_count: int
    mapped_count: int
    unresolved_count: int
    main_total_count: int
    main_mapped_count: int
    changed_count: int
    unchanged_count: int
    overall_coverage: float
    main_coverage: float
    cases: tuple[ReplayCaseResult, ...]


@dataclass(frozen=True)
class TaxonomyRollbackResult:
    run_id: UUID
    batch_id: UUID
    rolled_back: bool


@dataclass(frozen=True)
class _ReplayContext:
    batch: TestBatch
    document: Document
    version: TaxonomyVersion
    cases: tuple[TestCase, ...]
    test_points_by_id: dict[UUID, TestPoint]
    test_point_related_by_id: dict[UUID, tuple[UUID, ...]]
    case_related_by_id: dict[UUID, tuple[UUID, ...]]
    nodes_by_key: dict[str, StoredTaxonomyNode]
    mappings_by_id: dict[UUID, RequirementTaxonomyMapping]
    mapping_related_by_id: dict[UUID, tuple[UUID, ...]]
    versions_by_id: dict[UUID, TaxonomyVersion]


class TaxonomyReplayService:
    def __init__(self, session: AsyncSession, *, repository: TaxonomyRepository | None = None):
        self.session = session
        self.repository = repository or TaxonomyRepository(session)

    async def replay(
        self,
        assignments: TaxonomyAssignmentSet,
        *,
        apply: bool = False,
        expected_baseline_hash: str | None = None,
        expected_plan_hash: str | None = None,
        expected_legacy_anomaly_case_ids: frozenset[UUID] | None = None,
        actor: str | None = None,
    ) -> TaxonomyReplayResult:
        if apply and not expected_baseline_hash:
            raise TaxonomyReplayError("expected_baseline_hash_required", "apply 必须引用已审查的 dry-run baseline")
        if apply and not expected_plan_hash:
            raise TaxonomyReplayError("expected_plan_hash_required", "apply 必须引用已审查的 dry-run plan")
        if apply and assignments.approval_status != "approved":
            raise TaxonomyReplayError("assignment_set_not_approved", "apply 只接受已批准的 assignment set")
        normalized_actor = self._validated_actor(actor) if apply else None
        self._require_clean_transaction()
        async with self.session.begin():
            if apply:
                await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            context = await self._load_context(assignments, for_update=apply)
            if apply and _is_shadow_snapshot(context.batch):
                raise TaxonomyReplayError(
                    "replay_shadow_snapshot_apply_forbidden",
                    "远端 API 影子快照只能校准候选，不能作为 apply 基线",
                )
            baseline_hash = _baseline_hash(context)
            if apply and baseline_hash != expected_baseline_hash:
                raise TaxonomyReplayError("replay_baseline_changed", "batch/case/document 已在 dry-run 后变化")
            if apply and context.version.status != "active":
                raise TaxonomyReplayError("replay_version_not_active", f"version={context.version.version}")
            if apply and context.batch.status not in {"completed", "pending_review", "archived"}:
                raise TaxonomyReplayError("replay_batch_not_stable", f"status={context.batch.status}")
            if apply and context.batch.taxonomy_version_id not in {None, context.version.id}:
                raise TaxonomyReplayError(
                    "replay_batch_version_conflict",
                    str(context.batch.taxonomy_version_id),
                )

            digest = assignment_hash(assignments)
            plan_hash = _plan_hash(
                baseline_hash=baseline_hash,
                assignment_hash_value=digest,
                manifest_hash=assignments.manifest_hash,
                taxonomy_version_id=context.version.id,
                taxonomy_version=context.version.version,
                expected_legacy_anomaly_case_set_hash=(
                    _uuid_set_hash(expected_legacy_anomaly_case_ids)
                    if expected_legacy_anomaly_case_ids is not None
                    else None
                ),
            )
            if apply and plan_hash != expected_plan_hash:
                raise TaxonomyReplayError("replay_plan_changed", "manifest/assignment/version 已在 dry-run 后变化")
            run_id = uuid.uuid4() if apply else None
            result, proposed_states = _build_result(
                context,
                assignments,
                digest,
                baseline_hash,
                plan_hash,
                run_id=run_id,
            )
            if expected_legacy_anomaly_case_ids is not None:
                actual_anomaly_case_ids = frozenset(
                    case.case_id for case in result.cases if case.legacy_anomaly_category is not None
                )
                if actual_anomaly_case_ids != expected_legacy_anomaly_case_ids:
                    missing = sorted(
                        str(case_id) for case_id in expected_legacy_anomaly_case_ids - actual_anomaly_case_ids
                    )
                    extra = sorted(
                        str(case_id) for case_id in actual_anomaly_case_ids - expected_legacy_anomaly_case_ids
                    )
                    raise TaxonomyReplayError(
                        "legacy_anomaly_case_set_changed",
                        f"missing={missing[:5]} extra={extra[:5]}",
                    )
            if not apply:
                return result

            assert run_id is not None
            before_image = _before_image(context.batch, context.cases, context.case_related_by_id)
            context.batch.taxonomy_version_id = context.version.id
            related_rows: list[TestCaseRelatedTaxonomyConcept] = []
            applied_related_by_id: dict[UUID, tuple[UUID, ...]] = {}
            for case in context.cases:
                state = proposed_states[case.id]
                case.taxonomy_version_id = context.version.id
                case.taxonomy_concept_id = _uuid_or_none(state["taxonomy_concept_id"])
                case.taxonomy_resolution = state["taxonomy_resolution"]
                related_ids = tuple(UUID(value) for value in state["related_taxonomy_concept_ids"])
                applied_related_by_id[case.id] = related_ids
                related_rows.extend(
                    TestCaseRelatedTaxonomyConcept(
                        case_id=case.id,
                        taxonomy_version_id=context.version.id,
                        concept_id=concept_id,
                    )
                    for concept_id in related_ids
                )
            await self.session.flush()
            await self.repository.replace_case_related_concepts(
                {case.id for case in context.cases},
                related_rows,
            )

            applied_state_hash = _applied_state_hash(
                context.batch,
                context.cases,
                applied_related_by_id,
            )
            run = TaxonomyBackfillRun(
                id=run_id,
                batch_id=context.batch.id,
                taxonomy_version_id=context.version.id,
                manifest_hash=assignments.manifest_hash,
                assignment_hash=digest,
                baseline_hash=baseline_hash,
                plan_hash=plan_hash,
                applied_state_hash=applied_state_hash,
                actor=normalized_actor,
                status="applied",
                before_image=before_image,
                changed_count=result.changed_count,
                unchanged_count=result.unchanged_count,
                unresolved_count=result.unresolved_count,
            )
            await self.repository.add_backfill_run(run)
            return replace(
                result,
                applied=True,
                run_id=run.id,
                applied_state_hash=applied_state_hash,
            )

    async def rollback(self, run_id: UUID, *, actor: str) -> TaxonomyRollbackResult:
        normalized_actor = self._validated_actor(actor)
        self._require_clean_transaction()
        async with self.session.begin():
            await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            run = await self.repository.get_backfill_run(run_id, for_update=True)
            if run is None:
                raise TaxonomyReplayError("backfill_run_not_found", str(run_id))
            if run.status != "applied":
                raise TaxonomyReplayError("backfill_run_not_applied", f"status={run.status}")
            batch = await self.repository.get_batch(run.batch_id, for_update=True)
            if batch is None:
                raise TaxonomyReplayError("replay_batch_not_found", str(run.batch_id))
            cases = await self.repository.list_batch_cases(run.batch_id, for_update=True)
            current_related = await self.repository.get_case_related_concepts(
                {case.id for case in cases},
                for_update=True,
            )
            if _applied_state_hash(batch, cases, current_related) != run.applied_state_hash:
                raise TaxonomyReplayError("rollback_assignment_drift", "taxonomy 字段已在 apply 后变化")

            before = run.before_image
            before_cases = before.get("cases") if isinstance(before, dict) else None
            if not isinstance(before_cases, dict) or set(before_cases) != {str(case.id) for case in cases}:
                raise TaxonomyReplayError("rollback_before_image_invalid", "case 集合与 before-image 不一致")

            batch.taxonomy_version_id = _uuid_or_none(before.get("batch_taxonomy_version_id"))
            restored_related_rows: list[TestCaseRelatedTaxonomyConcept] = []
            for case in cases:
                state = before_cases[str(case.id)]
                restored_version_id = _uuid_or_none(state.get("taxonomy_version_id"))
                case.taxonomy_version_id = restored_version_id
                case.taxonomy_concept_id = _uuid_or_none(state.get("taxonomy_concept_id"))
                case.taxonomy_resolution = state.get("taxonomy_resolution")
                restored_related_ids = state.get("related_taxonomy_concept_ids", [])
                if restored_related_ids and restored_version_id is None:
                    raise TaxonomyReplayError(
                        "rollback_before_image_invalid",
                        f"case={case.id} related concepts 缺少 taxonomy version",
                    )
                if restored_version_id is not None:
                    restored_related_rows.extend(
                        TestCaseRelatedTaxonomyConcept(
                            case_id=case.id,
                            taxonomy_version_id=restored_version_id,
                            concept_id=UUID(value),
                        )
                        for value in restored_related_ids
                    )
            await self.repository.replace_case_related_concepts(
                {case.id for case in cases},
                restored_related_rows,
            )
            run.status = "rolled_back"
            run.rolled_back_by = normalized_actor
            run.rolled_back_at = datetime.now(timezone.utc)
            await self.session.flush()
            return TaxonomyRollbackResult(run_id=run.id, batch_id=batch.id, rolled_back=True)

    async def _load_context(
        self,
        assignments: TaxonomyAssignmentSet,
        *,
        for_update: bool,
    ) -> _ReplayContext:
        batch = await self.repository.get_batch(assignments.batch_id, for_update=for_update)
        if batch is None:
            raise TaxonomyReplayError("replay_batch_not_found", str(assignments.batch_id))
        document = await self.repository.get_document(batch.document_id, for_update=for_update)
        if document is None:
            raise TaxonomyReplayError("replay_document_not_found", str(batch.document_id))
        versions = await self.repository.list_versions(batch.system_id, for_update=for_update)
        version = next((item for item in versions if item.version == assignments.taxonomy_version), None)
        if version is None:
            raise TaxonomyReplayError("replay_version_not_found", str(assignments.taxonomy_version))
        if version.manifest_hash != assignments.manifest_hash:
            raise TaxonomyReplayError("replay_manifest_hash_mismatch", str(assignments.taxonomy_version))

        cases = tuple(await self.repository.list_batch_cases(batch.id, for_update=for_update))
        expected_case_ids = {case.id for case in cases}
        assignment_case_ids = {assignment.case_id for assignment in assignments.assignments}
        if expected_case_ids != assignment_case_ids:
            missing = sorted(str(case_id) for case_id in expected_case_ids - assignment_case_ids)
            extra = sorted(str(case_id) for case_id in assignment_case_ids - expected_case_ids)
            raise TaxonomyReplayError(
                "replay_case_set_mismatch",
                f"missing={missing[:5]} extra={extra[:5]}",
            )

        test_point_ids = {case.test_point_id for case in cases if case.test_point_id is not None}
        test_points = await self.repository.get_batch_test_points(
            batch.id,
            test_point_ids,
            for_update=for_update,
        )
        stored_nodes = await self.repository.list_nodes(version.id, for_update=for_update)
        nodes_by_key = {stored.concept.stable_key: stored for stored in stored_nodes}
        mappings = await self.repository.list_document_mappings(
            system_id=batch.system_id,
            document_id=document.id,
            document_content_hash=document.content_hash,
            for_update=for_update,
        )
        mappings_by_id = {mapping.id: mapping for mapping in mappings}
        mapping_ids = set(mappings_by_id)
        mapping_related_by_id = await self.repository.get_mapping_related_concepts(
            mapping_ids,
            for_update=for_update,
        )
        case_related_by_id = await self.repository.get_case_related_concepts(
            expected_case_ids,
            for_update=for_update,
        )
        test_point_related_by_id = await self.repository.get_test_point_related_concepts(
            test_point_ids,
            for_update=for_update,
        )
        context = _ReplayContext(
            batch=batch,
            document=document,
            version=version,
            cases=cases,
            test_points_by_id={point.id: point for point in test_points},
            test_point_related_by_id=test_point_related_by_id,
            case_related_by_id=case_related_by_id,
            nodes_by_key=nodes_by_key,
            mappings_by_id=mappings_by_id,
            mapping_related_by_id=mapping_related_by_id,
            versions_by_id={item.id: item for item in versions},
        )
        _validate_assignments(context, assignments)
        return context

    def _require_clean_transaction(self) -> None:
        if self.session.in_transaction():
            raise TaxonomyReplayError(
                "transaction_already_active",
                "TaxonomyReplayService 必须使用未开启事务的 session",
            )

    @staticmethod
    def _validated_actor(actor: str | None) -> str:
        normalized = (actor or "").strip()
        if not normalized:
            raise TaxonomyReplayError("actor_required", "写操作必须记录操作者")
        if len(normalized) > 100:
            raise TaxonomyReplayError("actor_too_long", "操作者长度不能超过 100")
        return normalized


def _validate_assignments(context: _ReplayContext, assignments: TaxonomyAssignmentSet) -> None:
    cases_by_id = {case.id: case for case in context.cases}
    for assignment in assignments.assignments:
        if assignment.assignment_source == "unresolved":
            continue
        target = context.nodes_by_key.get(assignment.target_stable_key or "")
        if target is None:
            raise TaxonomyReplayError("assignment_target_missing", str(assignment.target_stable_key))
        if target.node.node_status != "active":
            raise TaxonomyReplayError("assignment_target_not_active", str(assignment.target_stable_key))
        for related_key in assignment.related_stable_keys:
            related = context.nodes_by_key.get(related_key)
            if related is None or related.node.node_status != "active":
                raise TaxonomyReplayError("assignment_related_not_active", related_key)
        if assignment.assignment_source == "approved_mapping":
            _validate_approved_mapping(context, cases_by_id[assignment.case_id], assignment, target)


def _validate_approved_mapping(
    context: _ReplayContext,
    case: TestCase,
    assignment: TaxonomyCaseAssignment,
    target: StoredTaxonomyNode,
) -> None:
    if assignment.mapping_id is None:
        raise TaxonomyReplayError("assignment_mapping_id_missing", str(assignment.case_id))
    declared_mapping = context.mappings_by_id.get(assignment.mapping_id)
    if declared_mapping is None:
        raise TaxonomyReplayError("assignment_mapping_not_approved", str(assignment.mapping_id))
    test_point = context.test_points_by_id.get(case.test_point_id) if case.test_point_id else None
    mapping = _resolve_mapping_for_test_point(context, test_point)
    if mapping.id != declared_mapping.id:
        raise TaxonomyReplayError(
            "assignment_mapping_case_binding_unverifiable",
            str(assignment.case_id),
        )
    expected_related_ids = sorted(str(context.nodes_by_key[key].concept.id) for key in assignment.related_stable_keys)
    mapping_related_ids = sorted(str(value) for value in context.mapping_related_by_id.get(mapping.id, ()))
    if (
        mapping.system_id != context.batch.system_id
        or mapping.document_id != context.document.id
        or mapping.document_content_hash != context.document.content_hash
        or mapping.concept_id != target.concept.id
        or mapping_related_ids != expected_related_ids
        or mapping.reason != assignment.reason
        or mapping.confidence != assignment.confidence
    ):
        raise TaxonomyReplayError("assignment_mapping_context_mismatch", str(mapping.id))


def _resolve_mapping_for_test_point(
    context: _ReplayContext,
    test_point: TestPoint | None,
) -> RequirementTaxonomyMapping:
    if test_point is None or test_point.taxonomy_selector_facts is None:
        raise TaxonomyReplayError("assignment_mapping_selector_facts_missing", "TestPoint 缺少稳定 selector facts")
    try:
        facts = TaxonomySelectorFacts.model_validate(test_point.taxonomy_selector_facts)
    except ValidationError as exc:
        raise TaxonomyReplayError("assignment_mapping_selector_facts_invalid", str(test_point.id)) from exc

    candidates = [
        mapping
        for mapping in context.mappings_by_id.values()
        if mapping.feature_fingerprint == facts.feature_fingerprint and _mapping_is_valid_for_version(context, mapping)
    ]
    matching_selectors = [
        mapping
        for mapping in candidates
        if mapping.scope == "test_point_selector" and _mapping_selector_matches(mapping, facts)
    ]
    if len(matching_selectors) > 1:
        raise TaxonomyReplayError("assignment_mapping_selector_ambiguous", str(test_point.id))
    if matching_selectors:
        return matching_selectors[0]

    defaults = [mapping for mapping in candidates if mapping.scope == "feature_default"]
    if len(defaults) != 1:
        code = "assignment_mapping_default_ambiguous" if defaults else "assignment_mapping_no_match"
        raise TaxonomyReplayError(code, str(test_point.id))
    return defaults[0]


def _mapping_selector_matches(
    mapping: RequirementTaxonomyMapping,
    facts: TaxonomySelectorFacts,
) -> bool:
    try:
        selector = TaxonomySelector.model_validate(mapping.selector)
    except ValidationError as exc:
        raise TaxonomyReplayError("assignment_mapping_selector_invalid", str(mapping.id)) from exc
    if selector.rule_id is not None:
        return selector.rule_id == facts.rule_id
    if selector.structural_key is not None:
        return selector.structural_key == facts.structural_key
    assert selector.requirement_anchor is not None
    return selector.requirement_anchor in facts.requirement_anchors


def _mapping_is_valid_for_version(
    context: _ReplayContext,
    mapping: RequirementTaxonomyMapping,
) -> bool:
    start = context.versions_by_id.get(mapping.reviewed_taxonomy_version_id)
    if start is None:
        raise TaxonomyReplayError("assignment_mapping_version_missing", str(mapping.id))
    successors = [
        candidate for candidate in context.mappings_by_id.values() if candidate.supersedes_mapping_id == mapping.id
    ]
    if len(successors) > 1:
        raise TaxonomyReplayError("assignment_mapping_lineage_fork", str(mapping.id))
    successor_version: int | None = None
    if successors:
        successor = successors[0]
        successor_start = context.versions_by_id.get(successor.reviewed_taxonomy_version_id)
        if successor_start is None or successor_start.version <= start.version:
            raise TaxonomyReplayError("assignment_mapping_lineage_version_invalid", str(mapping.id))
        if _mapping_identity(successor) != _mapping_identity(mapping):
            raise TaxonomyReplayError("assignment_mapping_lineage_identity_mismatch", str(mapping.id))
        successor_version = successor_start.version
    if mapping.review_status == "superseded" and successor_version is None:
        raise TaxonomyReplayError("assignment_mapping_lineage_successor_missing", str(mapping.id))
    if mapping.review_status == "approved" and successor_version is not None:
        raise TaxonomyReplayError("assignment_mapping_lineage_head_status_invalid", str(mapping.id))
    return start.version <= context.version.version and (
        successor_version is None or context.version.version < successor_version
    )


def _mapping_identity(mapping: RequirementTaxonomyMapping) -> tuple[UUID, str, str, str, str]:
    return (
        mapping.document_id,
        mapping.document_content_hash,
        mapping.feature_fingerprint,
        mapping.scope,
        mapping.selector_hash,
    )


def _build_result(
    context: _ReplayContext,
    assignments: TaxonomyAssignmentSet,
    digest: str,
    baseline_hash: str,
    plan_hash: str,
    *,
    run_id: UUID | None,
) -> tuple[TaxonomyReplayResult, dict[UUID, dict[str, Any]]]:
    assignments_by_case = {assignment.case_id: assignment for assignment in assignments.assignments}
    paths = _node_paths(context.nodes_by_key)
    proposed_states: dict[UUID, dict[str, Any]] = {}
    case_results: list[ReplayCaseResult] = []
    mapped_count = 0
    main_total = 0
    main_mapped = 0
    changed_count = 0

    for case in context.cases:
        assignment = assignments_by_case[case.id]
        target = context.nodes_by_key.get(assignment.target_stable_key or "")
        legacy_module, legacy_branch_path, legacy = classify_case_tree_coordinates(
            {"title": case.title, "provenance": case.provenance}
        )
        legacy_classifier_module = str(legacy.get("business_module") or "_review_required")
        is_main = _is_main_candidate(case)
        main_total += int(is_main)
        if assignment.target_stable_key:
            mapped_count += 1
            main_mapped += int(is_main)
        state = _proposed_state(context, assignments, assignment, digest, plan_hash, run_id=run_id)
        proposed_states[case.id] = state
        changed = _current_case_state(case, context.case_related_by_id) != state
        changed_count += int(changed)
        case_results.append(
            ReplayCaseResult(
                case_id=case.id,
                title=case.title,
                priority=case.priority,
                bucket=case.bucket,
                verdict=case.verdict,
                is_main_candidate=is_main,
                source_refs=tuple(legacy.get("source_refs") or ()),
                legacy_classifier_module=legacy_classifier_module,
                legacy_business_module=legacy_module,
                legacy_branch_path=tuple(legacy_branch_path),
                legacy_confidence=str(legacy.get("classification_confidence") or "unresolved"),
                legacy_reason=str(legacy.get("classification_reason") or ""),
                legacy_anomaly_category=_legacy_anomaly_category(
                    legacy_module,
                    legacy_classifier_module,
                    legacy,
                ),
                old_taxonomy_concept_id=case.taxonomy_concept_id,
                target_stable_key=assignment.target_stable_key,
                target_node_type=target.node.node_type if target else None,
                related_stable_keys=tuple(sorted(assignment.related_stable_keys)),
                target_path=paths.get(assignment.target_stable_key or "", ()),
                assignment_source=assignment.assignment_source,
                reason=assignment.reason,
                confidence=assignment.confidence,
                unresolved_reason=assignment.unresolved_reason,
                changed=changed,
            )
        )

    total = len(context.cases)
    unresolved = total - mapped_count
    result = TaxonomyReplayResult(
        applied=False,
        run_id=None,
        batch_id=context.batch.id,
        source_scope="remote_api_shadow" if _is_shadow_snapshot(context.batch) else "database",
        taxonomy_version_id=context.version.id,
        taxonomy_version=context.version.version,
        manifest_hash=assignments.manifest_hash,
        assignment_hash=digest,
        baseline_hash=baseline_hash,
        plan_hash=plan_hash,
        case_set_hash=_case_set_hash(context.cases),
        provenance_hash=_provenance_hash(context.cases),
        applied_state_hash=None,
        total_count=total,
        mapped_count=mapped_count,
        unresolved_count=unresolved,
        main_total_count=main_total,
        main_mapped_count=main_mapped,
        changed_count=changed_count,
        unchanged_count=total - changed_count,
        overall_coverage=mapped_count / total if total else 0,
        main_coverage=main_mapped / main_total if main_total else 0,
        cases=tuple(case_results),
    )
    return result, proposed_states


def _proposed_state(
    context: _ReplayContext,
    assignments: TaxonomyAssignmentSet,
    assignment: TaxonomyCaseAssignment,
    digest: str,
    plan_hash: str,
    *,
    run_id: UUID | None,
) -> dict[str, Any]:
    target = context.nodes_by_key.get(assignment.target_stable_key or "")
    related_ids = [str(context.nodes_by_key[key].concept.id) for key in sorted(assignment.related_stable_keys)]
    resolution = {
        "schema_version": 1,
        "taxonomy_version_id": str(context.version.id),
        "manifest_hash": assignments.manifest_hash,
        "assignment_hash": digest,
        "plan_hash": plan_hash,
        "backfill_run_id": str(run_id) if run_id else None,
        "assignment_source": assignment.assignment_source,
        "target_stable_key": assignment.target_stable_key,
        "mapping_id": str(assignment.mapping_id) if assignment.mapping_id else None,
        "reason": assignment.reason,
        "confidence": assignment.confidence,
        "unresolved_reason": assignment.unresolved_reason,
        "prepared_by": assignments.prepared_by,
        "prepared_at": assignments.prepared_at.isoformat(),
        "approval_status": assignments.approval_status,
        "approved_by": assignments.approved_by,
        "approved_at": assignments.approved_at.isoformat() if assignments.approved_at else None,
    }
    return {
        "taxonomy_version_id": str(context.version.id),
        "taxonomy_concept_id": str(target.concept.id) if target else None,
        "related_taxonomy_concept_ids": related_ids,
        "taxonomy_resolution": resolution,
    }


def _node_paths(nodes_by_key: dict[str, StoredTaxonomyNode]) -> dict[str, tuple[str, ...]]:
    key_by_concept = {stored.concept.id: key for key, stored in nodes_by_key.items()}
    paths: dict[str, tuple[str, ...]] = {}

    def resolve(key: str) -> tuple[str, ...]:
        if key in paths:
            return paths[key]
        stored = nodes_by_key[key]
        parent_key = (
            key_by_concept.get(stored.node.parent_concept_id) if stored.node.parent_concept_id is not None else None
        )
        parent_path = resolve(parent_key) if parent_key else ()
        paths[key] = (*parent_path, stored.node.display_name)
        return paths[key]

    for stable_key in nodes_by_key:
        resolve(stable_key)
    return paths


def _is_main_candidate(case: TestCase) -> bool:
    return (
        case.review_status != "deleted"
        and case.duplicate_of is None
        and case.bucket == "main"
        and case.verdict == "grounded"
    )


def _is_shadow_snapshot(batch: TestBatch) -> bool:
    return bool((batch.generation_config or {}).get("shadow_snapshot"))


def _legacy_anomaly_category(
    legacy_module: str,
    classifier_module: str,
    classification: dict[str, Any],
) -> str | None:
    confidence = str(classification.get("classification_confidence") or "")
    if confidence == "legacy_source_section_fallback":
        return "source_section_fallback"
    if classifier_module == "_review_required" or legacy_module in {"待分类", "未分类"}:
        return "unresolved"
    if legacy_module == "提交底层与防超限":
        return "legacy_catch_all_module"
    return None


def _before_image(
    batch: TestBatch,
    cases: tuple[TestCase, ...] | list[TestCase],
    related_by_case_id: dict[UUID, tuple[UUID, ...]],
) -> dict[str, Any]:
    return {
        "batch_taxonomy_version_id": str(batch.taxonomy_version_id) if batch.taxonomy_version_id else None,
        "cases": {str(case.id): _current_case_state(case, related_by_case_id) for case in cases},
    }


def _current_case_state(
    case: TestCase,
    related_by_case_id: dict[UUID, tuple[UUID, ...]],
) -> dict[str, Any]:
    return {
        "taxonomy_version_id": str(case.taxonomy_version_id) if case.taxonomy_version_id else None,
        "taxonomy_concept_id": str(case.taxonomy_concept_id) if case.taxonomy_concept_id else None,
        "related_taxonomy_concept_ids": sorted(str(value) for value in related_by_case_id.get(case.id, ())),
        "taxonomy_resolution": case.taxonomy_resolution,
    }


def _baseline_hash(context: _ReplayContext) -> str:
    payload = {
        "batch": {
            "id": str(context.batch.id),
            "system_id": str(context.batch.system_id),
            "document_id": str(context.batch.document_id),
            "status": context.batch.status,
            "total_cases": context.batch.total_cases,
            "generation_config": context.batch.generation_config,
            "taxonomy_version_id": (
                str(context.batch.taxonomy_version_id) if context.batch.taxonomy_version_id else None
            ),
        },
        "document_content_hash": context.document.content_hash,
        "test_points": [
            _test_point_baseline(point, context.test_point_related_by_id)
            for point in sorted(context.test_points_by_id.values(), key=lambda item: item.id)
        ],
        "mappings": [
            _mapping_baseline(context, mapping)
            for mapping in sorted(context.mappings_by_id.values(), key=lambda item: item.id)
        ],
        "cases": [_case_baseline(case, context.case_related_by_id) for case in context.cases],
    }
    return _hash_payload(payload)


def _case_set_hash(cases: tuple[TestCase, ...] | list[TestCase]) -> str:
    return _hash_payload(sorted(str(case.id) for case in cases))


def _provenance_hash(cases: tuple[TestCase, ...] | list[TestCase]) -> str:
    return _hash_payload(
        [{"case_id": str(case.id), "provenance": case.provenance} for case in sorted(cases, key=lambda item: item.id)]
    )


def _case_baseline(
    case: TestCase,
    related_by_case_id: dict[UUID, tuple[UUID, ...]],
) -> dict[str, Any]:
    return {
        "id": str(case.id),
        "test_point_id": str(case.test_point_id) if case.test_point_id else None,
        "title": case.title,
        "preconditions": case.preconditions,
        "steps": case.steps,
        "expected_results": case.expected_results,
        "priority": case.priority,
        "dimensions": case.dimensions,
        "provenance": case.provenance,
        "trust_level": case.trust_level,
        "confidence_note": case.confidence_note,
        "review_status": case.review_status,
        "review_comment": case.review_comment,
        "iteration": case.iteration,
        "verdict": case.verdict,
        "bucket": case.bucket,
        "verification": case.verification,
        "duplicate_of": str(case.duplicate_of) if case.duplicate_of else None,
        **_current_case_state(case, related_by_case_id),
    }


def _test_point_baseline(
    point: TestPoint,
    related_by_test_point_id: dict[UUID, tuple[UUID, ...]],
) -> dict[str, Any]:
    return {
        "id": str(point.id),
        "feature_id": point.feature_id,
        "rule_id": str(point.rule_id) if point.rule_id else None,
        "taxonomy_selector_facts": point.taxonomy_selector_facts,
        "taxonomy_version_id": str(point.taxonomy_version_id) if point.taxonomy_version_id else None,
        "taxonomy_concept_id": str(point.taxonomy_concept_id) if point.taxonomy_concept_id else None,
        "related_taxonomy_concept_ids": sorted(str(value) for value in related_by_test_point_id.get(point.id, ())),
        "taxonomy_resolution": point.taxonomy_resolution,
    }


def _mapping_baseline(
    context: _ReplayContext,
    mapping: RequirementTaxonomyMapping,
) -> dict[str, Any]:
    reviewed_version = context.versions_by_id.get(mapping.reviewed_taxonomy_version_id)
    return {
        "id": str(mapping.id),
        "feature_fingerprint": mapping.feature_fingerprint,
        "scope": mapping.scope,
        "selector": mapping.selector,
        "selector_hash": mapping.selector_hash,
        "concept_id": str(mapping.concept_id),
        "related_concept_ids": sorted(str(value) for value in context.mapping_related_by_id.get(mapping.id, ())),
        "mapping_method": mapping.mapping_method,
        "confidence": mapping.confidence,
        "reason": mapping.reason,
        "review_status": mapping.review_status,
        "reviewed_by": mapping.reviewed_by,
        "reviewed_at": mapping.reviewed_at,
        "reviewed_taxonomy_version_id": str(mapping.reviewed_taxonomy_version_id),
        "reviewed_taxonomy_version": reviewed_version.version if reviewed_version else None,
        "supersedes_mapping_id": str(mapping.supersedes_mapping_id) if mapping.supersedes_mapping_id else None,
    }


def _applied_state_hash(
    batch: TestBatch,
    cases: tuple[TestCase, ...] | list[TestCase],
    related_by_case_id: dict[UUID, tuple[UUID, ...]],
) -> str:
    payload = {
        "batch_taxonomy_version_id": str(batch.taxonomy_version_id) if batch.taxonomy_version_id else None,
        "cases": {
            str(case.id): _current_case_state(case, related_by_case_id)
            for case in sorted(cases, key=lambda item: item.id)
        },
    }
    return _hash_payload(payload)


def _hash_payload(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plan_hash(
    *,
    baseline_hash: str,
    assignment_hash_value: str,
    manifest_hash: str,
    taxonomy_version_id: UUID,
    taxonomy_version: int,
    expected_legacy_anomaly_case_set_hash: str | None,
) -> str:
    return _hash_payload(
        {
            "baseline_hash": baseline_hash,
            "assignment_hash": assignment_hash_value,
            "manifest_hash": manifest_hash,
            "taxonomy_version_id": str(taxonomy_version_id),
            "taxonomy_version": taxonomy_version,
            "expected_legacy_anomaly_case_set_hash": expected_legacy_anomaly_case_set_hash,
        }
    )


def _uuid_set_hash(values: frozenset[UUID]) -> str:
    return _hash_payload(sorted(str(value) for value in values))


def _uuid_or_none(value: object) -> UUID | None:
    return UUID(str(value)) if value else None
