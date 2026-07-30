"""基于 active taxonomy 与新需求生成显式、不可直接应用的演进草案。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnit, RequirementUnitId
from src.testcase_generator.schemas.taxonomy import (
    Sha256,
    StableKey,
    TaxonomyExample,
    TaxonomyManifest,
    TaxonomyNodeManifest,
)
from src.testcase_generator.services.taxonomy_manifest import manifest_hash

EVOLUTION_PROMPT_REVISION = "taxonomy-evolution-v1"
EVOLUTION_ALGORITHM_REVISION = "taxonomy-evolution@2"

_EVOLUTION_SYSTEM_PROMPT = """你是 active 业务 taxonomy 的演进仲裁器。
输入只包含当前 immutable taxonomy 与尚未确定性复用的新 grounded requirement units。
规则：
1. 优先 no_change 或 alias；只有现有 definition/scope/aliases 都无法表达需求时才 add。
2. 所有变更必须用显式 operation：add/rename/move/split/merge/deprecate/no_change/alias。
3. 每个 requirement unit 必须且只能进入一个 operation 或 unresolved_requirement_unit_ids。
4. proposed node 必须引用输入 unit；不能创建无 evidence 父节点，不能按章节号/文档名/版本号复制目录。
5. stable key 是长期身份；文案变化不创建新 stable key，章节重排不视为业务变化。
6. 只输出 change proposal，不修改 active taxonomy，不声称已应用或激活。"""

StructuredGenerateFn = Callable[..., Awaitable[object]]
EvolutionProposalFn = Callable[["TaxonomyEvolutionRequest"], Awaitable[object]]

_SECTION_PREFIX = re.compile(
    r"^[#\s§]*(?:第\s*[一二三四五六七八九十百千零\d]+\s*[章节条款部分]?\s*[、,，.．:：\-—\s]*|"
    r"[一二三四五六七八九十百千零]+\s*[、,，.．:：\-—\s]+|"
    r"\d+(?:[.．]\d+)*[、,，.．:：\-—\s]+)"
)
_SEMANTIC_NAME = re.compile(r"[\s\u3000_\-–—、,，.．:：;；!?！？()（）\[\]【】<>《》/\\]+")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaxonomyEvolutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    max_context_chars: int = Field(ge=2_000, le=1_000_000)
    max_operations: int = Field(ge=1, le=5_000)
    fail_behavior: Literal["draft_only"] = "draft_only"

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class EvolutionNodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    display_name: str = Field(min_length=1, max_length=255)
    parent_stable_key: StableKey | None = None
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(min_length=1)
    scope_note: str = Field(min_length=1)
    requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sets(self) -> EvolutionNodeDraft:
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_evolution_node_alias")
        if len(self.requirement_unit_ids) != len(set(self.requirement_unit_ids)):
            raise ValueError("duplicate_evolution_node_evidence")
        if self.parent_stable_key == self.stable_key:
            raise ValueError("evolution_node_self_parent")
        return self


class TaxonomyEvolutionOperationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    operation: Literal["add", "rename", "move", "split", "merge", "deprecate", "no_change", "alias"]
    target_stable_keys: list[StableKey] = Field(default_factory=list)
    proposed_nodes: list[EvolutionNodeDraft] = Field(default_factory=list)
    new_display_name: str | None = Field(default=None, min_length=1, max_length=255)
    new_parent_stable_key: StableKey | None = None
    aliases_to_add: list[str] = Field(default_factory=list)
    replacement_stable_key: StableKey | None = None
    requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def validate_move_parent_is_explicit(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("operation") == "move" and "new_parent_stable_key" not in value:
            raise ValueError("evolution_move_parent_required")
        return value

    @model_validator(mode="after")
    def validate_operation_shape(self) -> TaxonomyEvolutionOperationDraft:
        if len(self.target_stable_keys) != len(set(self.target_stable_keys)):
            raise ValueError("duplicate_evolution_target")
        if len(self.aliases_to_add) != len(set(self.aliases_to_add)):
            raise ValueError("duplicate_evolution_alias")
        if len(self.requirement_unit_ids) != len(set(self.requirement_unit_ids)):
            raise ValueError("duplicate_evolution_requirement_unit")
        evidence_ids = set(self.requirement_unit_ids)
        if any(not set(node.requirement_unit_ids) <= evidence_ids for node in self.proposed_nodes):
            raise ValueError("evolution_node_evidence_outside_operation")

        parent_change_declared = self.new_parent_stable_key is not None
        change_fields = bool(
            self.proposed_nodes
            or self.new_display_name
            or self.aliases_to_add
            or self.replacement_stable_key
            or parent_change_declared
        )
        if self.operation == "add":
            if self.target_stable_keys:
                raise ValueError("evolution_add_target_forbidden")
            if not self.proposed_nodes:
                raise ValueError("evolution_add_node_required")
            if self.new_display_name or self.aliases_to_add or self.replacement_stable_key or parent_change_declared:
                raise ValueError("evolution_add_change_field_forbidden")
        elif self.operation == "no_change":
            self._require_one_target()
            if change_fields:
                raise ValueError("evolution_no_change_payload_forbidden")
        elif self.operation == "alias":
            self._require_one_target()
            if not self.aliases_to_add:
                raise ValueError("evolution_alias_required")
            if self.proposed_nodes or self.new_display_name or self.replacement_stable_key or parent_change_declared:
                raise ValueError("evolution_alias_payload_invalid")
        elif self.operation == "rename":
            self._require_one_target()
            if not self.new_display_name:
                raise ValueError("evolution_rename_display_required")
            if self.proposed_nodes or self.aliases_to_add or self.replacement_stable_key or parent_change_declared:
                raise ValueError("evolution_rename_payload_invalid")
        elif self.operation == "move":
            self._require_one_target()
            if self.proposed_nodes or self.new_display_name or self.aliases_to_add or self.replacement_stable_key:
                raise ValueError("evolution_move_payload_invalid")
        elif self.operation == "split":
            self._require_one_target()
            if len(self.proposed_nodes) < 2:
                raise ValueError("evolution_split_nodes_required")
            if self.new_display_name or self.aliases_to_add or self.replacement_stable_key or parent_change_declared:
                raise ValueError("evolution_split_payload_invalid")
        elif self.operation == "merge":
            if len(self.target_stable_keys) < 2:
                raise ValueError("evolution_merge_targets_required")
            if self.replacement_stable_key is None:
                raise ValueError("evolution_merge_replacement_required")
            if len(self.proposed_nodes) > 1 or self.new_display_name or self.aliases_to_add or parent_change_declared:
                raise ValueError("evolution_merge_payload_invalid")
        else:
            self._require_one_target()
            if self.proposed_nodes or self.new_display_name or self.aliases_to_add or parent_change_declared:
                raise ValueError("evolution_deprecate_payload_invalid")

        if self.proposed_nodes:
            proposed_evidence = {unit_id for node in self.proposed_nodes for unit_id in node.requirement_unit_ids}
            if proposed_evidence != evidence_ids:
                raise ValueError("evolution_proposed_node_evidence_incomplete")
        return self

    def _require_one_target(self) -> None:
        if len(self.target_stable_keys) != 1:
            raise ValueError("evolution_single_target_required")


class TaxonomyEvolutionDraftBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operations: list[TaxonomyEvolutionOperationDraft] = Field(default_factory=list)
    unresolved_requirement_unit_ids: list[RequirementUnitId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unresolved(self) -> TaxonomyEvolutionDraftBatch:
        if len(self.unresolved_requirement_unit_ids) != len(set(self.unresolved_requirement_unit_ids)):
            raise ValueError("duplicate_evolution_unresolved_unit")
        return self


class EvolutionActiveNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    display_name: str
    parent_stable_key: StableKey | None = None
    aliases: list[str]
    definition: str
    scope_note: str
    in_scope_examples: list[str]
    out_of_scope_examples: list[str]


class TaxonomyEvolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_nodes: list[EvolutionActiveNode]
    requirement_units: list[RequirementUnit]


@dataclass(frozen=True)
class TaxonomyEvolutionModelBinding:
    propose_changes: EvolutionProposalFn
    prompt_revision: str
    model_revision: str

    def __post_init__(self) -> None:
        if (
            not self.prompt_revision.strip()
            or not self.model_revision.strip()
            or self.prompt_revision != self.prompt_revision.strip()
            or self.model_revision != self.model_revision.strip()
        ):
            raise ValueError("taxonomy_evolution_binding_revision_required")


class EvolutionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_count: int = Field(default=0, ge=0)
    mapping_count: int = Field(default=0, ge=0)
    complete: bool
    missing_stable_keys: list[StableKey] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_completeness(self) -> EvolutionImpact:
        if self.complete == bool(self.missing_stable_keys):
            raise ValueError("evolution_impact_completeness_mismatch")
        if len(self.missing_stable_keys) != len(set(self.missing_stable_keys)):
            raise ValueError("duplicate_evolution_impact_missing_key")
        return self


class TaxonomyEvolutionOperation(TaxonomyEvolutionOperationDraft):
    operation_id: str = Field(pattern=r"^evo_[0-9a-f]{64}$")
    evidence: list[TaxonomyExample] = Field(min_length=1)
    before_nodes: list[TaxonomyNodeManifest] = Field(default_factory=list)
    impact: EvolutionImpact
    rollback: str = Field(min_length=1)


class TaxonomyEvolutionIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal[
        "input_invalid",
        "context_budget_exceeded",
        "model_failed",
        "operation_evidence_invalid",
        "operation_invalid",
    ]
    requirement_unit_ids: list[RequirementUnitId] = Field(default_factory=list)
    details: dict[str, str | int] = Field(default_factory=dict)


class TaxonomyEvolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    active_manifest_hash: Sha256
    input_hash: Sha256
    policy_version: Sha256
    prompt_revision: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    operations: list[TaxonomyEvolutionOperation] = Field(default_factory=list)
    proposal_hash: Sha256 | None = None
    unresolved_requirement_unit_ids: list[RequirementUnitId] = Field(default_factory=list)
    issues: list[TaxonomyEvolutionIssue] = Field(default_factory=list)
    review_required: Literal[True] = True
    apply_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_proposal_hash(self) -> TaxonomyEvolutionResult:
        expected = _operations_hash(self.operations) if self.operations else None
        if self.proposal_hash != expected:
            raise ValueError("evolution_proposal_hash_mismatch")
        return self

    @property
    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


def build_llm_taxonomy_evolution_binding(
    generate_structured: StructuredGenerateFn,
    *,
    model_revision: str,
) -> TaxonomyEvolutionModelBinding:
    model_revision = model_revision.strip()
    if not model_revision:
        raise ValueError("taxonomy_evolution_model_revision_required")

    async def propose(request: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        return TaxonomyEvolutionDraftBatch.model_validate(
            await generate_structured(
                _EVOLUTION_SYSTEM_PROMPT,
                _canonical_json(request),
                TaxonomyEvolutionDraftBatch,
                temperature=0,
                model_role="verify",
            )
        )

    return TaxonomyEvolutionModelBinding(
        propose_changes=propose,
        prompt_revision=EVOLUTION_PROMPT_REVISION,
        model_revision=model_revision,
    )


class TaxonomyEvolutionService:
    def __init__(self, *, policy: TaxonomyEvolutionPolicy):
        self.policy = policy

    async def evolve(
        self,
        *,
        active_manifest: TaxonomyManifest,
        requirement_units: list[RequirementUnit],
        model_binding: TaxonomyEvolutionModelBinding,
        impact_snapshot: dict[str, dict[str, int]],
    ) -> TaxonomyEvolutionResult:
        active_hash = manifest_hash(active_manifest)
        input_hash = build_taxonomy_evolution_input_hash(
            active_manifest_hash=active_hash,
            requirement_units=requirement_units,
            policy=self.policy,
            prompt_revision=model_binding.prompt_revision,
            model_revision=model_binding.model_revision,
            impact_snapshot=impact_snapshot,
        )

        def result(
            *,
            operations: list[TaxonomyEvolutionOperation] | None = None,
            unresolved: Iterable[str] = (),
            issues: list[TaxonomyEvolutionIssue] | None = None,
        ) -> TaxonomyEvolutionResult:
            resolved_operations = sorted(operations or [], key=lambda operation: operation.operation_id)
            return TaxonomyEvolutionResult(
                active_manifest_hash=active_hash,
                input_hash=input_hash,
                policy_version=self.policy.canonical_hash,
                prompt_revision=model_binding.prompt_revision,
                model_revision=model_binding.model_revision,
                operations=resolved_operations,
                proposal_hash=_operations_hash(resolved_operations) if resolved_operations else None,
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
            active_manifest.schema_version != 2
            or len(unit_ids) != len(set(unit_ids))
            or any(unit.system_id != active_manifest.system_id for unit in sorted_units)
        ):
            return result(
                unresolved=unit_ids,
                issues=[TaxonomyEvolutionIssue(code="input_invalid", requirement_unit_ids=unit_ids)],
            )

        active_nodes = [node for node in active_manifest.nodes if node.node_status == "active"]
        node_by_key = {node.stable_key: node for node in active_nodes}
        name_owners = _name_owners(active_nodes)
        unresolved: set[str] = {unit.unit_id for unit in sorted_units if unit.scope_status != "atomic"}
        deterministic_groups: dict[str, list[RequirementUnit]] = {}
        unmatched: list[RequirementUnit] = []
        for unit in sorted_units:
            if unit.scope_status != "atomic":
                continue
            target_key = unit.structural_key if unit.structural_key in node_by_key else None
            if target_key is None:
                owners = name_owners.get(_normalize_semantic_name(unit.title), set())
                if len(owners) == 1:
                    target_key = next(iter(owners))
            if target_key is None:
                unmatched.append(unit)
            else:
                deterministic_groups.setdefault(target_key, []).append(unit)

        drafts: list[TaxonomyEvolutionOperationDraft] = []
        for target_key, units in sorted(deterministic_groups.items()):
            node = node_by_key[target_key]
            existing_names = {_normalize_semantic_name(name) for name in [node.display_name, *node.aliases]}
            aliases = sorted(
                {
                    _strip_section_prefix(unit.title)
                    for unit in units
                    if _normalize_semantic_name(unit.title) not in existing_names
                }
            )
            drafts.append(
                TaxonomyEvolutionOperationDraft(
                    operation="alias" if aliases else "no_change",
                    target_stable_keys=[target_key],
                    aliases_to_add=aliases,
                    requirement_unit_ids=sorted(unit.unit_id for unit in units),
                    reason=(
                        "稳定业务身份已存在，仅补充新的业务别名。"
                        if aliases
                        else "稳定业务身份和现有名称已匹配，无需结构变更。"
                    ),
                )
            )

        issues: list[TaxonomyEvolutionIssue] = []
        if unmatched:
            request = TaxonomyEvolutionRequest(
                active_nodes=[_active_node_view(node) for node in active_nodes],
                requirement_units=unmatched,
            )
            if len(_canonical_json(request)) > self.policy.max_context_chars:
                unresolved.update(unit.unit_id for unit in unmatched)
                issues.append(
                    TaxonomyEvolutionIssue(
                        code="context_budget_exceeded",
                        requirement_unit_ids=[unit.unit_id for unit in unmatched],
                    )
                )
                return self._materialize_or_fail(
                    result=result,
                    active_hash=active_hash,
                    active_manifest=active_manifest,
                    drafts=drafts,
                    units=sorted_units,
                    unresolved=unresolved,
                    issues=issues,
                    impact_snapshot=impact_snapshot,
                )
            try:
                model_draft = TaxonomyEvolutionDraftBatch.model_validate(await model_binding.propose_changes(request))
            except Exception as exc:  # noqa: BLE001 - 模型异常不泄露供应商正文
                unresolved.update(unit.unit_id for unit in unmatched)
                issues.append(
                    TaxonomyEvolutionIssue(
                        code="model_failed",
                        requirement_unit_ids=[unit.unit_id for unit in unmatched],
                        details={"error_type": type(exc).__name__},
                    )
                )
                return self._materialize_or_fail(
                    result=result,
                    active_hash=active_hash,
                    active_manifest=active_manifest,
                    drafts=drafts,
                    units=sorted_units,
                    unresolved=unresolved,
                    issues=issues,
                    impact_snapshot=impact_snapshot,
                )

            unmatched_ids = {unit.unit_id for unit in unmatched}
            referenced = [unit_id for operation in model_draft.operations for unit_id in operation.requirement_unit_ids]
            referenced.extend(model_draft.unresolved_requirement_unit_ids)
            if set(referenced) != unmatched_ids or len(referenced) != len(set(referenced)):
                unresolved.update(unmatched_ids)
                issues.append(
                    TaxonomyEvolutionIssue(
                        code="operation_evidence_invalid",
                        requirement_unit_ids=sorted(unmatched_ids),
                    )
                )
                return self._materialize_or_fail(
                    result=result,
                    active_hash=active_hash,
                    active_manifest=active_manifest,
                    drafts=drafts,
                    units=sorted_units,
                    unresolved=unresolved,
                    issues=issues,
                    impact_snapshot=impact_snapshot,
                )
            drafts.extend(model_draft.operations)
            unresolved.update(model_draft.unresolved_requirement_unit_ids)

        return self._materialize_or_fail(
            result=result,
            active_hash=active_hash,
            active_manifest=active_manifest,
            drafts=drafts,
            units=sorted_units,
            unresolved=unresolved,
            issues=issues,
            impact_snapshot=impact_snapshot,
        )

    def _materialize_or_fail(
        self,
        *,
        result: Callable[..., TaxonomyEvolutionResult],
        active_hash: str,
        active_manifest: TaxonomyManifest,
        drafts: list[TaxonomyEvolutionOperationDraft],
        units: list[RequirementUnit],
        unresolved: set[str],
        issues: list[TaxonomyEvolutionIssue],
        impact_snapshot: dict[str, dict[str, int]],
    ) -> TaxonomyEvolutionResult:
        try:
            if len(drafts) > self.policy.max_operations:
                raise ValueError("evolution_operation_limit_exceeded")
            operations = _materialize_operations(
                active_manifest=active_manifest,
                active_hash=active_hash,
                drafts=drafts,
                units=units,
                impact_snapshot=impact_snapshot,
            )
        except Exception as exc:  # noqa: BLE001 - 坏 change set 不得部分应用
            issues.append(
                TaxonomyEvolutionIssue(
                    code="operation_invalid",
                    requirement_unit_ids=[unit.unit_id for unit in units],
                    details={"error_type": type(exc).__name__},
                )
            )
            return result(unresolved=[unit.unit_id for unit in units], issues=issues)
        if manifest_hash(active_manifest) != active_hash:
            raise RuntimeError("active_manifest_mutated_during_evolution")
        return result(operations=operations, unresolved=unresolved, issues=issues)


def _materialize_operations(
    *,
    active_manifest: TaxonomyManifest,
    active_hash: str,
    drafts: list[TaxonomyEvolutionOperationDraft],
    units: list[RequirementUnit],
    impact_snapshot: dict[str, dict[str, int]],
) -> list[TaxonomyEvolutionOperation]:
    active_by_key = {node.stable_key: node for node in active_manifest.nodes if node.node_status == "active"}
    unit_by_id = {unit.unit_id: unit for unit in units}
    proposed_nodes = [node for draft in drafts for node in draft.proposed_nodes]
    proposed_keys = [node.stable_key for node in proposed_nodes]
    if len(proposed_keys) != len(set(proposed_keys)) or set(proposed_keys) & set(active_by_key):
        raise ValueError("evolution_proposed_stable_key_conflict")
    available_keys = set(active_by_key) | set(proposed_keys)
    if any(
        node.parent_stable_key is not None and node.parent_stable_key not in available_keys for node in proposed_nodes
    ):
        raise ValueError("evolution_proposed_parent_missing")

    target_usage: list[str] = [target for draft in drafts for target in draft.target_stable_keys]
    if len(target_usage) != len(set(target_usage)):
        raise ValueError("evolution_target_changed_multiple_times")
    if any(target not in active_by_key for target in target_usage):
        raise ValueError("evolution_target_missing")
    if any(
        draft.replacement_stable_key is not None and draft.replacement_stable_key not in available_keys
        for draft in drafts
    ):
        raise ValueError("evolution_replacement_missing")

    _validate_proposed_graph(active_by_key, proposed_nodes, drafts)
    _validate_name_changes(active_by_key, drafts)
    operations: list[TaxonomyEvolutionOperation] = []
    for draft in drafts:
        if any(unit_id not in unit_by_id for unit_id in draft.requirement_unit_ids):
            raise ValueError("evolution_operation_evidence_unknown")
        evidence_units = [unit_by_id[unit_id] for unit_id in sorted(draft.requirement_unit_ids)]
        normalized_draft = _normalize_draft_names(draft)
        before_nodes = [active_by_key[key] for key in normalized_draft.target_stable_keys]
        impact = _combined_impact(normalized_draft.target_stable_keys, impact_snapshot)
        # JSON 往返后无法保留“原响应是否省略可选字段”，operation 身份不能依赖该进程内状态。
        operation_payload = normalized_draft.model_dump(mode="json")
        operation_digest = _canonical_hash(
            {
                "active_manifest_hash": active_hash,
                "operation": operation_payload,
                "evidence_hashes": [unit.evidence_hash for unit in evidence_units],
            }
        )
        operation_id = f"evo_{operation_digest}"
        operations.append(
            TaxonomyEvolutionOperation(
                **operation_payload,
                operation_id=operation_id,
                evidence=[
                    TaxonomyExample(
                        text=unit.source_quote,
                        document_content_hash=unit.document_content_hash,
                        requirement_unit_id=unit.unit_id,
                    )
                    for unit in evidence_units
                ],
                before_nodes=before_nodes,
                impact=impact,
                rollback=_rollback_for(normalized_draft.operation),
            )
        )
    return operations


def _validate_name_changes(
    active_by_key: dict[str, TaxonomyNodeManifest],
    drafts: list[TaxonomyEvolutionOperationDraft],
) -> None:
    owner_by_name = _name_owners(active_by_key.values())
    for draft in drafts:
        target = draft.target_stable_keys[0] if len(draft.target_stable_keys) == 1 else None
        candidate_names: list[str] = []
        if draft.new_display_name:
            candidate_names.append(draft.new_display_name)
        candidate_names.extend(draft.aliases_to_add)
        for node in draft.proposed_nodes:
            candidate_names.extend([node.display_name, *node.aliases])
        for name in candidate_names:
            normalized = _normalize_semantic_name(name)
            owners = owner_by_name.get(normalized, set())
            if draft.operation == "alias" and owners == {target}:
                raise ValueError("evolution_alias_already_present")
            if draft.operation == "rename" and owners == {target}:
                raise ValueError("evolution_rename_is_no_change")
            if owners and owners != ({target} if target is not None else set()):
                raise ValueError("evolution_semantic_name_conflict")
            owner_key = target or next(
                (node.stable_key for node in draft.proposed_nodes if name == node.display_name or name in node.aliases),
                "proposed",
            )
            owner_by_name.setdefault(normalized, set()).add(owner_key)


def _validate_proposed_graph(
    active_by_key: dict[str, TaxonomyNodeManifest],
    proposed_nodes: list[EvolutionNodeDraft],
    drafts: list[TaxonomyEvolutionOperationDraft],
) -> None:
    parent_by_key: dict[str, str | None] = {key: node.parent_stable_key for key, node in active_by_key.items()}
    type_by_key = {key: node.node_type for key, node in active_by_key.items()}
    for node in proposed_nodes:
        parent_by_key[node.stable_key] = node.parent_stable_key
        type_by_key[node.stable_key] = node.node_type
    for draft in drafts:
        if draft.operation == "move":
            parent_by_key[draft.target_stable_keys[0]] = draft.new_parent_stable_key

    for key, parent_key in parent_by_key.items():
        if parent_key is None:
            continue
        if parent_key not in parent_by_key:
            raise ValueError("evolution_graph_parent_missing")
        if type_by_key[parent_key] == "capability":
            raise ValueError("evolution_capability_cannot_parent")
        if type_by_key[key] == "domain" and type_by_key[parent_key] != "domain":
            raise ValueError("evolution_domain_parent_invalid")

    for start in parent_by_key:
        visited: set[str] = set()
        current: str | None = start
        while current is not None:
            if current in visited:
                raise ValueError("evolution_graph_cycle")
            visited.add(current)
            current = parent_by_key[current]


def _normalize_draft_names(draft: TaxonomyEvolutionOperationDraft) -> TaxonomyEvolutionOperationDraft:
    payload = draft.model_dump(mode="python", exclude_unset=True)
    if payload.get("new_display_name") is not None:
        payload["new_display_name"] = _strip_section_prefix(payload["new_display_name"])
    if "aliases_to_add" in payload:
        payload["aliases_to_add"] = [_strip_section_prefix(alias) for alias in draft.aliases_to_add]
    if "proposed_nodes" in payload:
        payload["proposed_nodes"] = [
            {
                **node.model_dump(mode="python", exclude_unset=True),
                "display_name": _strip_section_prefix(node.display_name),
                "aliases": [_strip_section_prefix(alias) for alias in node.aliases],
            }
            for node in draft.proposed_nodes
        ]
    return TaxonomyEvolutionOperationDraft.model_validate(payload)


def _active_node_view(node: TaxonomyNodeManifest) -> EvolutionActiveNode:
    assert node.definition is not None
    assert node.scope_note is not None
    return EvolutionActiveNode(
        stable_key=node.stable_key,
        node_type=node.node_type,
        display_name=node.display_name,
        parent_stable_key=node.parent_stable_key,
        aliases=node.aliases,
        definition=node.definition,
        scope_note=node.scope_note,
        in_scope_examples=[example.text for example in (node.in_scope_examples or [])],
        out_of_scope_examples=[example.text for example in (node.out_of_scope_examples or [])],
    )


def _combined_impact(
    target_keys: list[str],
    impact_snapshot: dict[str, dict[str, int]],
) -> EvolutionImpact:
    missing_keys = sorted(key for key in target_keys if key not in impact_snapshot)
    impacts = [
        EvolutionImpact(
            **impact_snapshot[key],
            complete=True,
            missing_stable_keys=[],
        )
        for key in target_keys
        if key in impact_snapshot
    ]
    return EvolutionImpact(
        case_count=sum(impact.case_count for impact in impacts),
        mapping_count=sum(impact.mapping_count for impact in impacts),
        complete=not missing_keys,
        missing_stable_keys=missing_keys,
    )


def _rollback_for(operation: str) -> str:
    return {
        "no_change": "无需回滚；未提议结构变更。",
        "alias": "移除本次新增别名并恢复前一 taxonomy version。",
        "add": "弃用新增节点并恢复前一 taxonomy version。",
        "rename": "恢复原 display name 和前一 taxonomy version。",
        "move": "恢复原 parent 关系和前一 taxonomy version。",
        "split": "撤销拆分节点并恢复原节点。",
        "merge": "恢复合并前节点及其映射。",
        "deprecate": "恢复节点 active 状态和原映射。",
    }[operation]


def _name_owners(nodes: Iterable[TaxonomyNodeManifest]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for node in nodes:
        for name in [node.display_name, *node.aliases]:
            owners.setdefault(_normalize_semantic_name(name), set()).add(node.stable_key)
    return owners


def _strip_section_prefix(value: str) -> str:
    if re.fullmatch(r"[#\s§]*\d+(?:[.．]\d+)*[、,，.．:：\-—\s]*", value):
        raise ValueError("evolution_display_name_only_section_number")
    stripped = _SECTION_PREFIX.sub("", value.strip())
    if not stripped:
        raise ValueError("evolution_display_name_empty_after_section_strip")
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


def _operations_hash(operations: list[TaxonomyEvolutionOperation]) -> str:
    payload = [
        operation.model_dump(mode="json") for operation in sorted(operations, key=lambda item: item.operation_id)
    ]
    return _canonical_hash(payload)


def build_taxonomy_evolution_input_hash(
    *,
    active_manifest_hash: str,
    requirement_units: list[RequirementUnit],
    policy: TaxonomyEvolutionPolicy,
    prompt_revision: str,
    model_revision: str,
    impact_snapshot: dict[str, dict[str, int]],
) -> str:
    payload = {
        "algorithm_revision": EVOLUTION_ALGORITHM_REVISION,
        "active_manifest_hash": active_manifest_hash,
        "requirement_units": [
            unit.model_dump(mode="json") for unit in sorted(requirement_units, key=lambda item: item.unit_id)
        ],
        "policy_version": policy.canonical_hash,
        "prompt_revision": prompt_revision,
        "model_revision": model_revision,
        "impact_snapshot": impact_snapshot,
    }
    return _canonical_hash(payload)


def validate_taxonomy_evolution_result_replay(
    *,
    active_manifest: TaxonomyManifest,
    requirement_units: list[RequirementUnit],
    policy: TaxonomyEvolutionPolicy,
    result: TaxonomyEvolutionResult,
    impact_snapshot: dict[str, dict[str, int]],
) -> None:
    """重放 evolve 的确定性封装；不重放模型生成本身。"""

    canonical_issues = sorted(
        result.issues,
        key=lambda issue: (
            issue.code,
            issue.requirement_unit_ids,
            json.dumps(issue.details, sort_keys=True),
        ),
    )
    if (
        result.operations != sorted(result.operations, key=lambda operation: operation.operation_id)
        or result.unresolved_requirement_unit_ids != sorted(set(result.unresolved_requirement_unit_ids))
        or result.issues != canonical_issues
    ):
        raise ValueError("evolution_result_canonical_order_invalid")

    active_hash = manifest_hash(active_manifest)
    expected_input_hash = build_taxonomy_evolution_input_hash(
        active_manifest_hash=active_hash,
        requirement_units=requirement_units,
        policy=policy,
        prompt_revision=result.prompt_revision,
        model_revision=result.model_revision,
        impact_snapshot=impact_snapshot,
    )
    if (
        result.active_manifest_hash != active_hash
        or result.policy_version != policy.canonical_hash
        or result.input_hash != expected_input_hash
    ):
        raise ValueError("evolution_result_input_binding_mismatch")

    drafts = [
        TaxonomyEvolutionOperationDraft.model_validate(
            operation.model_dump(
                mode="python",
                exclude={"operation_id", "evidence", "before_nodes", "impact", "rollback"},
            )
        )
        for operation in result.operations
    ]
    replayed = _materialize_operations(
        active_manifest=active_manifest,
        active_hash=active_hash,
        drafts=drafts,
        units=sorted(requirement_units, key=lambda item: item.unit_id),
        impact_snapshot=impact_snapshot,
    )
    if replayed != result.operations:
        raise ValueError("evolution_result_operation_replay_mismatch")
