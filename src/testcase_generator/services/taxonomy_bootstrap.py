"""从 grounded requirement units 生成仅供审查的 taxonomy v2 草案。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnit, RequirementUnitId
from src.testcase_generator.schemas.taxonomy import (
    Sha256,
    StableKey,
    TaxonomyExample,
    TaxonomyManifest,
    TaxonomyNodeManifest,
)
from src.testcase_generator.schemas.taxonomy_resolution import bootstrap_proposal_id
from src.testcase_generator.services.taxonomy_manifest import manifest_hash

BOOTSTRAP_PROPOSAL_PROMPT_REVISION = "taxonomy-bootstrap-proposal-v1"
BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION = "taxonomy-bootstrap-consolidation-v1"
BOOTSTRAP_ALGORITHM_REVISION = "taxonomy-bootstrap@1"

_PROPOSAL_SYSTEM_PROMPT = """你是业务能力归纳器，只处理输入中的 grounded atomic requirement units。
规则：
1. 每个输入 unit 必须且只能出现在一个 proposal 或 unresolved_requirement_unit_ids 中。
2. proposal 表达稳定业务责任，不按 PRD 章节号、页面标题或测试用例措辞建目录。
3. definition/scope 只能概括输入事实，不补充常识；requirement_unit_ids 只能引用当前批次。
4. 同一批次内语义相同的 units 合并为一个 proposal；无法判断时 unresolved。
5. 不生成 domain/module 层级，不输出 schema 之外字段。"""

_CONSOLIDATION_SYSTEM_PROMPT = """你是业务 taxonomy 草案仲裁器，只处理输入的 grounded capability proposals。
规则：
1. 同义 proposal 合并到同一目标节点，不能为每份 PRD 或每个章节复制节点。
2. 层级按稳定业务责任组织；module 可以直接承载 proposal，也可包含真实分支，不强制 domain/module/capability 三层齐全。
3. 每个节点必须引用至少一个 source_proposal_id，父节点也不能是无来源的装饰目录。
4. 每个 proposal 必须且只能 assignment 到一个最具体目标节点。
5. display name 不带章节号；stable key 一旦导入将成为稳定身份，不使用版本号或文档名。
6. 只输出 draft，不声称已激活，不输出输入之外的业务事实。"""

StructuredGenerateFn = Callable[..., Awaitable[object]]
CapabilityProposalFn = Callable[["BootstrapUnitBatch"], Awaitable[object]]
StructureConsolidationFn = Callable[["BootstrapConsolidationRequest"], Awaitable[object]]

_SECTION_PREFIX = re.compile(
    r"^[#\s§]*(?:第\s*[一二三四五六七八九十百千零\d]+\s*[章节条款部分]?\s*[、,，.．:：\-—\s]*|"
    r"[一二三四五六七八九十百千零]+\s*[、,，.．:：\-—\s]+|"
    r"\d+(?:[.．]\d+)*[、,，.．:：\-—\s]+)"
)
_SEMANTIC_NAME = re.compile(r"[\s\u3000_\-–—、,，.．:：;；!?！？()（）\[\]【】<>《》/\\]+")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaxonomyBootstrapPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    max_units_per_batch: int = Field(ge=1, le=50)
    max_batch_chars: int = Field(ge=1_000, le=200_000)
    max_consolidation_chars: int = Field(ge=2_000, le=1_000_000)
    max_nodes: int = Field(ge=1, le=5_000)
    fail_behavior: Literal["draft_only"] = "draft_only"

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class BootstrapUnitBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_index: int = Field(ge=1)
    batch_count: int = Field(ge=1)
    units: list[RequirementUnit] = Field(max_length=50)


class BootstrapCapabilityDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    stable_key: StableKey
    display_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(min_length=1)
    scope_note: str = Field(min_length=1)
    requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sets(self) -> BootstrapCapabilityDraft:
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_bootstrap_alias")
        if len(self.requirement_unit_ids) != len(set(self.requirement_unit_ids)):
            raise ValueError("duplicate_bootstrap_requirement_unit")
        return self


class BootstrapCapabilityDraftBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: list[BootstrapCapabilityDraft] = Field(default_factory=list, max_length=50)
    unresolved_requirement_unit_ids: list[RequirementUnitId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unresolved(self) -> BootstrapCapabilityDraftBatch:
        if len(self.unresolved_requirement_unit_ids) != len(set(self.unresolved_requirement_unit_ids)):
            raise ValueError("duplicate_bootstrap_unresolved_unit")
        return self


class BootstrapCapabilityProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    proposal_id: str = Field(pattern=r"^bp_[0-9a-f]{64}$")
    stable_key: StableKey
    display_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(min_length=1)
    scope_note: str = Field(min_length=1)
    requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)
    evidence_hashes: list[Sha256] = Field(min_length=1)
    evidence: list[TaxonomyExample] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence(self) -> BootstrapCapabilityProposal:
        if len(self.requirement_unit_ids) != len(set(self.requirement_unit_ids)):
            raise ValueError("duplicate_bootstrap_proposal_unit")
        evidence_unit_ids = [example.requirement_unit_id for example in self.evidence]
        if len(evidence_unit_ids) != len(set(evidence_unit_ids)):
            raise ValueError("duplicate_bootstrap_proposal_evidence")
        if set(evidence_unit_ids) != set(self.requirement_unit_ids):
            raise ValueError("bootstrap_proposal_evidence_mismatch")
        if len(self.evidence_hashes) != len(self.requirement_unit_ids):
            raise ValueError("bootstrap_proposal_evidence_hash_mismatch")
        if bootstrap_proposal_id(self.evidence_hashes) != self.proposal_id:
            raise ValueError("bootstrap_proposal_id_mismatch")
        return self


class BootstrapConsolidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: list[BootstrapCapabilityProposal] = Field(min_length=1)


class BootstrapNodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    node_key: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=160)
    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    display_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(min_length=1)
    scope_note: str = Field(min_length=1)
    parent_node_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
        max_length=160,
    )
    source_proposal_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sets(self) -> BootstrapNodeDraft:
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_bootstrap_node_alias")
        if len(self.source_proposal_ids) != len(set(self.source_proposal_ids)):
            raise ValueError("duplicate_bootstrap_node_source")
        if self.parent_node_key == self.node_key:
            raise ValueError("bootstrap_node_self_parent")
        return self


class BootstrapProposalAssignmentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(pattern=r"^bp_[0-9a-f]{64}$")
    target_node_key: str = Field(
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
        max_length=160,
    )


class BootstrapStructureDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: list[BootstrapNodeDraft]
    assignments: list[BootstrapProposalAssignmentDraft]


class BootstrapStructureDraftBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    structure: BootstrapStructureDraft


@dataclass(frozen=True)
class TaxonomyBootstrapModelBinding:
    propose_capabilities: CapabilityProposalFn
    consolidate_structure: StructureConsolidationFn
    proposal_prompt_revision: str
    consolidation_prompt_revision: str
    proposal_model_revision: str
    consolidation_model_revision: str

    def __post_init__(self) -> None:
        values = (
            self.proposal_prompt_revision,
            self.consolidation_prompt_revision,
            self.proposal_model_revision,
            self.consolidation_model_revision,
        )
        if any(not value.strip() or value != value.strip() for value in values):
            raise ValueError("taxonomy_bootstrap_binding_revision_required")


class TaxonomyBootstrapIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal[
        "input_unit_invalid",
        "unit_context_budget_exceeded",
        "proposal_model_failed",
        "proposal_evidence_invalid",
        "consolidation_context_budget_exceeded",
        "consolidation_model_failed",
        "structure_invalid",
    ]
    requirement_unit_ids: list[RequirementUnitId] = Field(default_factory=list)
    details: dict[str, str | int] = Field(default_factory=dict)


class BootstrapRequirementAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_unit_id: RequirementUnitId
    proposal_id: str = Field(pattern=r"^bp_[0-9a-f]{64}$")
    target_stable_key: StableKey


class TaxonomyBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_prompt_revision: str = Field(min_length=1)
    consolidation_prompt_revision: str = Field(min_length=1)
    proposal_model_revision: str = Field(min_length=1)
    consolidation_model_revision: str = Field(min_length=1)
    draft_manifest: TaxonomyManifest | None = None
    draft_manifest_hash: Sha256 | None = None
    proposals: list[BootstrapCapabilityProposal] = Field(default_factory=list)
    assignments: list[BootstrapRequirementAssignment] = Field(default_factory=list)
    unresolved_requirement_unit_ids: list[RequirementUnitId] = Field(default_factory=list)
    issues: list[TaxonomyBootstrapIssue] = Field(default_factory=list)
    review_required: Literal[True] = True
    activation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_manifest_hash(self) -> TaxonomyBootstrapResult:
        if (self.draft_manifest is None) != (self.draft_manifest_hash is None):
            raise ValueError("bootstrap_manifest_hash_pair_required")
        if self.draft_manifest is not None and manifest_hash(self.draft_manifest) != self.draft_manifest_hash:
            raise ValueError("bootstrap_manifest_hash_mismatch")
        return self

    @property
    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


def build_llm_taxonomy_bootstrap_binding(
    generate_structured: StructuredGenerateFn,
    *,
    proposal_model_revision: str,
    consolidation_model_revision: str,
) -> TaxonomyBootstrapModelBinding:
    proposal_model_revision = proposal_model_revision.strip()
    consolidation_model_revision = consolidation_model_revision.strip()
    if not proposal_model_revision or not consolidation_model_revision:
        raise ValueError("taxonomy_bootstrap_model_revision_required")

    async def propose(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch.model_validate(
            await generate_structured(
                _PROPOSAL_SYSTEM_PROMPT,
                _canonical_json(batch),
                BootstrapCapabilityDraftBatch,
                temperature=0,
                model_role="primary",
            )
        )

    async def consolidate(request: BootstrapConsolidationRequest) -> BootstrapStructureDraftBatch:
        return BootstrapStructureDraftBatch.model_validate(
            await generate_structured(
                _CONSOLIDATION_SYSTEM_PROMPT,
                _canonical_json(request),
                BootstrapStructureDraftBatch,
                temperature=0,
                model_role="verify",
            )
        )

    return TaxonomyBootstrapModelBinding(
        propose_capabilities=propose,
        consolidate_structure=consolidate,
        proposal_prompt_revision=BOOTSTRAP_PROPOSAL_PROMPT_REVISION,
        consolidation_prompt_revision=BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION,
        proposal_model_revision=proposal_model_revision,
        consolidation_model_revision=consolidation_model_revision,
    )


class TaxonomyBootstrapService:
    def __init__(self, *, policy: TaxonomyBootstrapPolicy):
        self.policy = policy

    async def bootstrap(
        self,
        *,
        system_id: UUID,
        version: int,
        change_note: str,
        created_by: str,
        requirement_units: list[RequirementUnit],
        model_binding: TaxonomyBootstrapModelBinding,
    ) -> TaxonomyBootstrapResult:
        input_hash = _bootstrap_input_hash(
            system_id=system_id,
            version=version,
            change_note=change_note,
            created_by=created_by,
            requirement_units=requirement_units,
            policy=self.policy,
            model_binding=model_binding,
        )

        def result(
            *,
            draft_manifest: TaxonomyManifest | None = None,
            proposals: list[BootstrapCapabilityProposal] | None = None,
            assignments: list[BootstrapRequirementAssignment] | None = None,
            unresolved: Iterable[str] = (),
            issues: list[TaxonomyBootstrapIssue] | None = None,
        ) -> TaxonomyBootstrapResult:
            return TaxonomyBootstrapResult(
                input_hash=input_hash,
                policy_version=self.policy.canonical_hash,
                proposal_prompt_revision=model_binding.proposal_prompt_revision,
                consolidation_prompt_revision=model_binding.consolidation_prompt_revision,
                proposal_model_revision=model_binding.proposal_model_revision,
                consolidation_model_revision=model_binding.consolidation_model_revision,
                draft_manifest=draft_manifest,
                draft_manifest_hash=manifest_hash(draft_manifest) if draft_manifest is not None else None,
                proposals=proposals or [],
                assignments=assignments or [],
                unresolved_requirement_unit_ids=sorted(set(unresolved)),
                issues=sorted(
                    issues or [],
                    key=lambda issue: (
                        issue.code,
                        issue.requirement_unit_ids,
                        json.dumps(issue.details, sort_keys=True),
                    ),
                ),
            )

        sorted_units = sorted(requirement_units, key=lambda unit: unit.unit_id)
        unit_ids = [unit.unit_id for unit in sorted_units]
        if (
            len(unit_ids) != len(set(unit_ids))
            or any(unit.system_id != system_id for unit in sorted_units)
            or version < 1
            or not change_note.strip()
            or not created_by.strip()
        ):
            return result(
                unresolved=unit_ids,
                issues=[TaxonomyBootstrapIssue(code="input_unit_invalid", requirement_unit_ids=unit_ids)],
            )

        unresolved: set[str] = {unit.unit_id for unit in sorted_units if unit.scope_status != "atomic"}
        eligible: list[RequirementUnit] = []
        issues: list[TaxonomyBootstrapIssue] = []
        for unit in sorted_units:
            if unit.scope_status != "atomic":
                continue
            if len(_canonical_json(BootstrapUnitBatch(batch_index=1, batch_count=1, units=[unit]))) > (
                self.policy.max_batch_chars
            ):
                unresolved.add(unit.unit_id)
                issues.append(
                    TaxonomyBootstrapIssue(
                        code="unit_context_budget_exceeded",
                        requirement_unit_ids=[unit.unit_id],
                    )
                )
                continue
            eligible.append(unit)

        groups = _batch_units(eligible, self.policy)
        batches = [
            BootstrapUnitBatch(
                batch_index=index,
                batch_count=len(groups),
                units=group,
            )
            for index, group in enumerate(groups, start=1)
        ]
        unit_by_id = {unit.unit_id: unit for unit in eligible}
        proposals: list[BootstrapCapabilityProposal] = []
        for batch in batches:
            try:
                draft_batch = BootstrapCapabilityDraftBatch.model_validate(
                    await model_binding.propose_capabilities(batch)
                )
            except Exception as exc:  # noqa: BLE001 - 外部模型失败只保留固定类型
                issues.append(
                    TaxonomyBootstrapIssue(
                        code="proposal_model_failed",
                        requirement_unit_ids=[unit.unit_id for unit in batch.units],
                        details={"error_type": type(exc).__name__},
                    )
                )
                return result(unresolved=unit_ids, issues=issues)

            batch_ids = {unit.unit_id for unit in batch.units}
            referenced = [unit_id for proposal in draft_batch.proposals for unit_id in proposal.requirement_unit_ids]
            referenced.extend(draft_batch.unresolved_requirement_unit_ids)
            if set(referenced) != batch_ids or len(referenced) != len(set(referenced)):
                issues.append(
                    TaxonomyBootstrapIssue(
                        code="proposal_evidence_invalid",
                        requirement_unit_ids=sorted(batch_ids),
                    )
                )
                return result(unresolved=unit_ids, issues=issues)

            unresolved.update(draft_batch.unresolved_requirement_unit_ids)
            try:
                for draft in draft_batch.proposals:
                    evidence_units = [unit_by_id[unit_id] for unit_id in draft.requirement_unit_ids]
                    evidence_hashes = sorted(unit.evidence_hash for unit in evidence_units)
                    proposals.append(
                        BootstrapCapabilityProposal(
                            proposal_id=bootstrap_proposal_id(evidence_hashes),
                            stable_key=draft.stable_key,
                            display_name=_strip_section_prefix(draft.display_name),
                            aliases=[_strip_section_prefix(alias) for alias in draft.aliases],
                            definition=draft.definition,
                            scope_note=draft.scope_note,
                            requirement_unit_ids=sorted(draft.requirement_unit_ids),
                            evidence_hashes=evidence_hashes,
                            evidence=[
                                TaxonomyExample(
                                    text=unit.source_quote,
                                    document_content_hash=unit.document_content_hash,
                                    requirement_unit_id=unit.unit_id,
                                )
                                for unit in sorted(evidence_units, key=lambda item: item.unit_id)
                            ],
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - 模型草案后处理也必须 fail closed
                issues.append(
                    TaxonomyBootstrapIssue(
                        code="proposal_evidence_invalid",
                        requirement_unit_ids=sorted(batch_ids),
                        details={"error_type": type(exc).__name__},
                    )
                )
                return result(unresolved=unit_ids, issues=issues)

        proposals.sort(key=lambda proposal: (proposal.proposal_id, proposal.stable_key))
        if len({proposal.proposal_id for proposal in proposals}) != len(proposals):
            issues.append(TaxonomyBootstrapIssue(code="proposal_evidence_invalid"))
            return result(unresolved=unit_ids, issues=issues)
        if not proposals:
            return result(unresolved=unresolved, issues=issues)

        consolidation_request = BootstrapConsolidationRequest(proposals=proposals)
        if len(_canonical_json(consolidation_request)) > self.policy.max_consolidation_chars:
            issues.append(TaxonomyBootstrapIssue(code="consolidation_context_budget_exceeded"))
            return result(proposals=proposals, unresolved=unit_ids, issues=issues)
        try:
            structure = BootstrapStructureDraftBatch.model_validate(
                await model_binding.consolidate_structure(consolidation_request)
            ).structure
        except Exception as exc:  # noqa: BLE001 - 外部模型失败只保留固定类型
            issues.append(
                TaxonomyBootstrapIssue(
                    code="consolidation_model_failed",
                    details={"error_type": type(exc).__name__},
                )
            )
            return result(proposals=proposals, unresolved=unit_ids, issues=issues)

        try:
            manifest, assignments = _materialize_structure(
                system_id=system_id,
                version=version,
                change_note=change_note.strip(),
                created_by=created_by.strip(),
                structure=structure,
                proposals=proposals,
                unit_by_id=unit_by_id,
                max_nodes=self.policy.max_nodes,
            )
        except Exception as exc:  # noqa: BLE001 - 坏结构只形成 draft issue
            issues.append(
                TaxonomyBootstrapIssue(
                    code="structure_invalid",
                    details={"error_type": type(exc).__name__},
                )
            )
            return result(proposals=proposals, unresolved=unit_ids, issues=issues)

        assigned_ids = {assignment.requirement_unit_id for assignment in assignments}
        unresolved.update(set(unit_ids) - assigned_ids)
        return result(
            draft_manifest=manifest,
            proposals=proposals,
            assignments=assignments,
            unresolved=unresolved,
            issues=issues,
        )


def _batch_units(
    units: list[RequirementUnit],
    policy: TaxonomyBootstrapPolicy,
) -> list[list[RequirementUnit]]:
    groups: list[list[RequirementUnit]] = []
    current: list[RequirementUnit] = []
    for unit in units:
        candidate = [*current, unit]
        candidate_payload = BootstrapUnitBatch(batch_index=1, batch_count=1, units=candidate)
        if current and (
            len(candidate) > policy.max_units_per_batch
            or len(_canonical_json(candidate_payload)) > policy.max_batch_chars
        ):
            groups.append(current)
            current = [unit]
        else:
            current = candidate
    if current:
        groups.append(current)
    return groups


def _materialize_structure(
    *,
    system_id: UUID,
    version: int,
    change_note: str,
    created_by: str,
    structure: BootstrapStructureDraft,
    proposals: list[BootstrapCapabilityProposal],
    unit_by_id: dict[str, RequirementUnit],
    max_nodes: int,
) -> tuple[TaxonomyManifest, list[BootstrapRequirementAssignment]]:
    if not structure.nodes or len(structure.nodes) > max_nodes:
        raise ValueError("bootstrap_node_count_invalid")
    node_by_key = {node.node_key: node for node in structure.nodes}
    if len(node_by_key) != len(structure.nodes):
        raise ValueError("duplicate_bootstrap_node_key")
    if len({node.stable_key for node in structure.nodes}) != len(structure.nodes):
        raise ValueError("duplicate_bootstrap_stable_key")
    _validate_semantic_names(structure.nodes)

    proposal_by_id = {proposal.proposal_id: proposal for proposal in proposals}
    assignment_by_proposal = {assignment.proposal_id: assignment for assignment in structure.assignments}
    if len(assignment_by_proposal) != len(structure.assignments):
        raise ValueError("duplicate_bootstrap_assignment")
    if set(assignment_by_proposal) != set(proposal_by_id):
        raise ValueError("bootstrap_proposal_assignment_incomplete")

    children: dict[str, list[str]] = {}
    for node in structure.nodes:
        if any(proposal_id not in proposal_by_id for proposal_id in node.source_proposal_ids):
            raise ValueError("bootstrap_node_source_unknown")
        if node.parent_node_key is not None:
            parent = node_by_key.get(node.parent_node_key)
            if parent is None:
                raise ValueError("bootstrap_parent_missing")
            if parent.node_type == "capability":
                raise ValueError("bootstrap_capability_cannot_parent")
            if node.node_type == "domain" and parent.node_type != "domain":
                raise ValueError("bootstrap_domain_parent_invalid")
            children.setdefault(parent.node_key, []).append(node.node_key)
    _assert_acyclic(node_by_key)
    if any(assignment.target_node_key not in node_by_key for assignment in structure.assignments):
        raise ValueError("bootstrap_assignment_target_missing")
    if any(node_by_key[assignment.target_node_key].node_type == "domain" for assignment in structure.assignments):
        raise ValueError("bootstrap_domain_assignment_forbidden")
    if any(
        proposal_id not in node_by_key[assignment.target_node_key].source_proposal_ids
        for proposal_id, assignment in assignment_by_proposal.items()
    ):
        raise ValueError("bootstrap_assignment_target_source_mismatch")
    direct_assignments: dict[str, set[str]] = {}
    for proposal_id, assignment in assignment_by_proposal.items():
        direct_assignments.setdefault(assignment.target_node_key, set()).add(proposal_id)
    for node in structure.nodes:
        subtree_proposals: set[str] = set()
        stack = [node.node_key]
        while stack:
            current = stack.pop()
            subtree_proposals.update(direct_assignments.get(current, set()))
            stack.extend(children.get(current, []))
        if set(node.source_proposal_ids) != subtree_proposals:
            raise ValueError("bootstrap_node_subtree_evidence_mismatch")

    stable_by_node_key = {node.node_key: node.stable_key for node in structure.nodes}
    sibling_order: dict[str | None, dict[str, int]] = {}
    for parent_key in {node.parent_node_key for node in structure.nodes}:
        siblings = sorted(
            (node for node in structure.nodes if node.parent_node_key == parent_key),
            key=lambda node: (node.stable_key, node.node_key),
        )
        sibling_order[parent_key] = {node.node_key: index for index, node in enumerate(siblings)}

    manifest_nodes: list[TaxonomyNodeManifest] = []
    for node in sorted(structure.nodes, key=lambda item: (item.stable_key, item.node_key)):
        evidence_units = _node_evidence_units(node, proposal_by_id, unit_by_id)
        manifest_nodes.append(
            TaxonomyNodeManifest(
                stable_key=node.stable_key,
                node_type=node.node_type,
                display_name=_strip_section_prefix(node.display_name),
                parent_stable_key=(
                    stable_by_node_key[node.parent_node_key] if node.parent_node_key is not None else None
                ),
                aliases=[_strip_section_prefix(alias) for alias in node.aliases],
                sort_order=sibling_order[node.parent_node_key][node.node_key],
                node_status="active",
                definition=node.definition,
                scope_note=node.scope_note,
                in_scope_examples=[
                    TaxonomyExample(
                        text=unit.source_quote,
                        document_content_hash=unit.document_content_hash,
                        requirement_unit_id=unit.unit_id,
                    )
                    for unit in evidence_units
                ],
                out_of_scope_examples=[],
            )
        )

    assignments: list[BootstrapRequirementAssignment] = []
    for proposal_id, assignment in sorted(assignment_by_proposal.items()):
        target = node_by_key[assignment.target_node_key]
        for unit_id in proposal_by_id[proposal_id].requirement_unit_ids:
            assignments.append(
                BootstrapRequirementAssignment(
                    requirement_unit_id=unit_id,
                    proposal_id=proposal_id,
                    target_stable_key=target.stable_key,
                )
            )
    if len({assignment.requirement_unit_id for assignment in assignments}) != len(assignments):
        raise ValueError("duplicate_bootstrap_requirement_assignment")

    manifest = TaxonomyManifest(
        schema_version=2,
        system_id=system_id,
        version=version,
        change_note=change_note,
        created_by=created_by,
        nodes=manifest_nodes,
        mappings=[],
    )
    return manifest, sorted(assignments, key=lambda assignment: assignment.requirement_unit_id)


def _node_evidence_units(
    node: BootstrapNodeDraft,
    proposal_by_id: dict[str, BootstrapCapabilityProposal],
    unit_by_id: dict[str, RequirementUnit],
) -> list[RequirementUnit]:
    unit_ids = {
        unit_id
        for proposal_id in node.source_proposal_ids
        for unit_id in proposal_by_id[proposal_id].requirement_unit_ids
    }
    if not unit_ids or any(unit_id not in unit_by_id for unit_id in unit_ids):
        raise ValueError("bootstrap_node_evidence_missing")
    return [unit_by_id[unit_id] for unit_id in sorted(unit_ids)]


def _assert_acyclic(node_by_key: dict[str, BootstrapNodeDraft]) -> None:
    for start in node_by_key:
        visited: set[str] = set()
        current: str | None = start
        while current is not None:
            if current in visited:
                raise ValueError("bootstrap_hierarchy_cycle")
            visited.add(current)
            current = node_by_key[current].parent_node_key


def _validate_semantic_names(nodes: list[BootstrapNodeDraft]) -> None:
    owner_by_name: dict[str, str] = {}
    for node in nodes:
        names = [node.display_name, *node.aliases]
        for name in names:
            normalized = _normalize_semantic_name(name)
            if not normalized:
                raise ValueError("bootstrap_semantic_name_empty")
            owner = owner_by_name.get(normalized)
            if owner is not None and owner != node.node_key:
                raise ValueError("duplicate_bootstrap_semantic_name")
            owner_by_name[normalized] = node.node_key


def _strip_section_prefix(value: str) -> str:
    if re.fullmatch(r"[#\s§]*\d+(?:[.．]\d+)*[、,，.．:：\-—\s]*", value):
        raise ValueError("bootstrap_display_name_only_section_number")
    stripped = _SECTION_PREFIX.sub("", value.strip())
    if not stripped:
        raise ValueError("bootstrap_display_name_empty_after_section_strip")
    return stripped


def _normalize_semantic_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", _strip_section_prefix(value)).casefold()
    return _SEMANTIC_NAME.sub("", normalized)


def _canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _bootstrap_input_hash(
    *,
    system_id: UUID,
    version: int,
    change_note: str,
    created_by: str,
    requirement_units: list[RequirementUnit],
    policy: TaxonomyBootstrapPolicy,
    model_binding: TaxonomyBootstrapModelBinding,
) -> str:
    payload = {
        "algorithm_revision": BOOTSTRAP_ALGORITHM_REVISION,
        "system_id": str(system_id),
        "version": version,
        "change_note": change_note.strip(),
        "created_by": created_by.strip(),
        "requirement_units": [
            unit.model_dump(mode="json") for unit in sorted(requirement_units, key=lambda item: item.unit_id)
        ],
        "policy_version": policy.canonical_hash,
        "proposal_prompt_revision": model_binding.proposal_prompt_revision,
        "consolidation_prompt_revision": model_binding.consolidation_prompt_revision,
        "proposal_model_revision": model_binding.proposal_model_revision,
        "consolidation_model_revision": model_binding.consolidation_model_revision,
    }
    return _canonical_hash(payload)
