"""从带来源锚点的 PRD 章节提取可回放的原子需求单元。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.parsed_context import SectionExtract, SectionKind
from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)

RequirementUnitScopeStatus = Literal["atomic", "wide", "unsupported", "conflicted"]
REQUIREMENT_UNIT_PROMPT_REVISION = "requirement-unit-v1"
REQUIREMENT_UNIT_VERIFIER_PROMPT_REVISION = "requirement-unit-verifier-v1"

_REQUIREMENT_UNIT_SYSTEM_PROMPT = """你是需求事实原子化器，只处理当前给出的 PRD 章节片段。
规则：
1. 只引用当前输入中的原文，不得使用测试用例标题、常识或其他章节补全事实。
2. 每个 unit 只表达一个可独立观察的业务结果；能拆分的联合描述必须拆成多个 unit。
3. source_quote 必须逐字摘自当前 content，不能改写、拼接或省略关键条件。
4. 无法可靠拆分的联合约束标为 wide；来源不足标为 unsupported；原文明示冲突标为 conflicted。
5. structural_key 只描述稳定业务能力，不使用章节编号或测试用例编号。
6. 如果片段没有任何可独立验证的需求，明确返回 disposition=no_requirement 和原因；不能只返回空数组。
7. 不生成目录节点，不推断实现机制，不输出当前 schema 以外字段。"""

_REQUIREMENT_UNIT_VERIFIER_SYSTEM_PROMPT = """你是独立需求证据核验器。
你只能检查输入中每个 unit 自带的 source_quote，不能使用常识、其他章节或测试用例补全事实。
逐项判断 source_quote 是否同时蕴含 statement、observable_outcome 和 structural_key 所表达的业务能力。
只要任一字段增加了原文没有支持的业务行为，就判 not_entailed；不得因 quote 确实存在而放行。
必须覆盖所有输入 requirement_unit_id，不能新增、遗漏或重复 ID。"""


class DocumentSnapshotMismatchError(ValueError):
    pass


class RequirementUnitDraft(BaseModel):
    """局部原子化器的强类型输出；来源位置由服务端注入。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_quote: str = Field(min_length=1)
    structural_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1)
    observable_outcome: str = Field(min_length=1)
    scope_status: RequirementUnitScopeStatus


class RequirementUnitDraftBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["requirements_extracted", "no_requirement"]
    reason: str | None = Field(default=None, min_length=1)
    units: list[RequirementUnitDraft] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_disposition(self) -> RequirementUnitDraftBatch:
        if self.disposition == "requirements_extracted" and not self.units:
            raise ValueError("requirement_batch_disposition_mismatch")
        if self.disposition == "no_requirement":
            if self.units:
                raise ValueError("requirement_batch_disposition_mismatch")
            if not self.reason:
                raise ValueError("requirement_batch_no_requirement_reason_required")
        return self


class RequirementExtractionChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ref: str = Field(min_length=1, max_length=1000)
    heading: str = Field(min_length=1, max_length=500)
    section_kind: SectionKind
    chunk_index: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequirementUnitIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_ref: str = Field(min_length=1, max_length=1000)
    chunk_index: int | None = Field(default=None, ge=1)
    code: Literal[
        "section_not_induction_eligible",
        "empty_section",
        "extractor_failed",
        "source_quote_not_grounded",
        "duplicate_unit_payload_conflict",
        "semantic_evidence_not_entailed",
        "semantic_verifier_failed",
    ]
    details: dict[str, str | int] = Field(default_factory=dict)


RequirementCoverageDisposition = Literal[
    "requirements_extracted",
    "no_requirement",
    "excluded_non_spec",
    "empty_section",
    "failed",
]


def build_requirement_coverage_id(
    *,
    document_content_hash: str,
    source_ref: str,
    chunk_index: int,
    content_hash: str,
) -> str:
    payload = json.dumps(
        {
            "document_content_hash": document_content_hash,
            "source_ref": source_ref,
            "chunk_index": chunk_index,
            "content_hash": content_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"rc_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


class RequirementChunkCoverage(BaseModel):
    """源分母中的一个确定性 chunk 及其处置，零 unit 也不能消失。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    coverage_id: str = Field(pattern=r"^rc_[0-9a-f]{64}$")
    source_ref: str = Field(min_length=1, max_length=1000)
    heading: str = Field(min_length=1, max_length=500)
    section_kind: SectionKind
    chunk_index: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: RequirementCoverageDisposition
    requirement_unit_ids: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_disposition(self) -> RequirementChunkCoverage:
        if len(self.requirement_unit_ids) != len(set(self.requirement_unit_ids)):
            raise ValueError("requirement_coverage_duplicate_unit")
        if self.disposition == "requirements_extracted":
            if not self.requirement_unit_ids or self.reason is not None:
                raise ValueError("requirement_coverage_disposition_mismatch")
        elif self.requirement_unit_ids or not self.reason:
            raise ValueError("requirement_coverage_disposition_mismatch")
        return self


class RequirementUnitSemanticVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    requirement_unit_id: str = Field(pattern=r"^ru_[0-9a-f]{64}$")
    verdict: Literal["entailed", "not_entailed"]
    reason: str = Field(min_length=1)


class RequirementUnitVerificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verifications: list[RequirementUnitSemanticVerification] = Field(default_factory=list, max_length=50)


class RequirementUnitExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    document_id: UUID
    document_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_revision: str = Field(min_length=1, max_length=255)
    model_revision: str = Field(min_length=1, max_length=255)
    verifier_prompt_revision: str | None = Field(default=None, min_length=1, max_length=255)
    verifier_model_revision: str | None = Field(default=None, min_length=1, max_length=255)
    chunk_count: int = Field(ge=0)
    units: list[RequirementUnit] = Field(default_factory=list)
    coverage: list[RequirementChunkCoverage] = Field(default_factory=list)
    semantic_verifications: list[RequirementUnitSemanticVerification] = Field(default_factory=list)
    issues: list[RequirementUnitIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_coverage_and_verification(self) -> RequirementUnitExtractionResult:
        coverage_ids = [item.coverage_id for item in self.coverage]
        if len(coverage_ids) != len(set(coverage_ids)) or self.chunk_count != len(self.coverage):
            raise ValueError("requirement_coverage_incomplete")
        coverage_groups: dict[
            tuple[str, str, SectionKind],
            list[RequirementChunkCoverage],
        ] = {}
        for item in self.coverage:
            coverage_groups.setdefault(
                (item.source_ref, item.heading, item.section_kind),
                [],
            ).append(item)
        for group in coverage_groups.values():
            chunk_counts = {item.chunk_count for item in group}
            indices = sorted(item.chunk_index for item in group)
            if len(chunk_counts) != 1 or indices != list(range(1, next(iter(chunk_counts)) + 1)):
                raise ValueError("requirement_coverage_chunk_sequence_invalid")
        unit_id_list = [item.unit_id for item in self.units]
        if len(unit_id_list) != len(set(unit_id_list)):
            raise ValueError("requirement_unit_identity_duplicate")
        unit_ids = set(unit_id_list)
        covered_ids = {unit_id for item in self.coverage for unit_id in item.requirement_unit_ids}
        if covered_ids != unit_ids:
            raise ValueError("requirement_coverage_unit_mismatch")
        verification_ids = [item.requirement_unit_id for item in self.semantic_verifications]
        if len(verification_ids) != len(set(verification_ids)):
            raise ValueError("requirement_semantic_verification_duplicate")
        if (self.verifier_prompt_revision is None) != (self.verifier_model_revision is None):
            raise ValueError("requirement_verifier_revision_pair_required")
        if self.verifier_prompt_revision is not None and set(verification_ids) != unit_ids:
            raise ValueError("requirement_semantic_verification_incomplete")
        if self.verifier_prompt_revision is None and self.semantic_verifications:
            raise ValueError("requirement_semantic_verification_without_revision")
        return self


RequirementUnitExtractor = Callable[[RequirementExtractionChunk], Awaitable[object]]
RequirementUnitVerifier = Callable[[list[RequirementUnit]], Awaitable[object]]
StructuredGenerateFn = Callable[..., Awaitable[RequirementUnitDraftBatch]]


@dataclass(frozen=True)
class RequirementUnitExtractorBinding:
    extractor: RequirementUnitExtractor
    prompt_revision: str
    model_revision: str


@dataclass(frozen=True)
class RequirementUnitVerifierBinding:
    verifier: RequirementUnitVerifier
    prompt_revision: str
    model_revision: str


def build_llm_requirement_unit_extractor(
    generate_structured: StructuredGenerateFn,
    *,
    model_revision: str,
) -> RequirementUnitExtractorBinding:
    """把现有 structured LLM client 绑定为只读当前 chunk 的原子化器。"""

    model_revision = model_revision.strip()
    if not model_revision:
        raise ValueError("requirement_extractor_model_revision_required")

    async def extract(chunk: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        user_content = json.dumps(
            chunk.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return await generate_structured(
            _REQUIREMENT_UNIT_SYSTEM_PROMPT,
            user_content,
            RequirementUnitDraftBatch,
            temperature=0,
            model_role="primary",
        )

    return RequirementUnitExtractorBinding(
        extractor=extract,
        prompt_revision=REQUIREMENT_UNIT_PROMPT_REVISION,
        model_revision=model_revision,
    )


def build_llm_requirement_unit_verifier(
    generate_structured: Callable[..., Awaitable[RequirementUnitVerificationBatch]],
    *,
    model_revision: str,
) -> RequirementUnitVerifierBinding:
    model_revision = model_revision.strip()
    if not model_revision:
        raise ValueError("requirement_verifier_model_revision_required")

    async def verify(units: list[RequirementUnit]) -> RequirementUnitVerificationBatch:
        payload = [
            {
                "requirement_unit_id": unit.unit_id,
                "source_quote": unit.source_quote,
                "structural_key": unit.structural_key,
                "statement": unit.statement,
                "observable_outcome": unit.observable_outcome,
            }
            for unit in units
        ]
        return await generate_structured(
            _REQUIREMENT_UNIT_VERIFIER_SYSTEM_PROMPT,
            json.dumps({"units": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            RequirementUnitVerificationBatch,
            temperature=0,
            model_role="verify",
        )

    return RequirementUnitVerifierBinding(
        verifier=verify,
        prompt_revision=REQUIREMENT_UNIT_VERIFIER_PROMPT_REVISION,
        model_revision=model_revision,
    )


def build_requirement_chunks(
    section: SectionExtract,
    *,
    max_chars: int = 6000,
    overlap_chars: int = 400,
) -> list[RequirementExtractionChunk]:
    """用有重叠的完整窗口覆盖 section；不使用会丢中段的 head/tail 截断。"""

    if max_chars < 64:
        raise ValueError("requirement_chunk_max_chars_too_small")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("requirement_chunk_overlap_invalid")

    content = section.content.strip()
    if not content:
        return []

    windows = _complete_windows(content, max_chars=max_chars, overlap_chars=overlap_chars)

    chunk_count = len(windows)
    return [
        RequirementExtractionChunk(
            source_ref=section.source_ref,
            heading=section.heading,
            section_kind=section.section_kind,
            chunk_index=index,
            chunk_count=chunk_count,
            content=window,
            content_hash=hashlib.sha256(window.encode("utf-8")).hexdigest(),
        )
        for index, window in enumerate(windows, start=1)
    ]


class RequirementUnitService:
    def __init__(
        self,
        *,
        max_chunk_chars: int = 6000,
        chunk_overlap_chars: int = 400,
        concurrency: int = 4,
        eligible_section_kinds: frozenset[SectionKind] = frozenset({"spec"}),
    ):
        if concurrency < 1:
            raise ValueError("requirement_extraction_concurrency_invalid")
        self.max_chunk_chars = max_chunk_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.concurrency = concurrency
        self.eligible_section_kinds = eligible_section_kinds

    async def extract(
        self,
        *,
        system_id: UUID,
        document_id: UUID,
        document_content_hash: str,
        document_snapshot: str,
        sections: list[SectionExtract],
        extractor: RequirementUnitExtractor,
        prompt_revision: str,
        model_revision: str,
        verifier: RequirementUnitVerifier | None = None,
        verifier_prompt_revision: str | None = None,
        verifier_model_revision: str | None = None,
    ) -> RequirementUnitExtractionResult:
        prompt_revision = prompt_revision.strip()
        model_revision = model_revision.strip()
        if not prompt_revision or not model_revision:
            raise ValueError("requirement_extractor_revision_required")
        verifier_prompt_revision = verifier_prompt_revision.strip() if verifier_prompt_revision else None
        verifier_model_revision = verifier_model_revision.strip() if verifier_model_revision else None
        if (verifier is None) != (verifier_prompt_revision is None) or (verifier is None) != (
            verifier_model_revision is None
        ):
            raise ValueError("requirement_verifier_binding_incomplete")
        actual_hash = hashlib.sha256(document_snapshot.encode("utf-8")).hexdigest()
        if actual_hash != document_content_hash:
            raise DocumentSnapshotMismatchError(
                f"document_snapshot_hash_mismatch: expected={document_content_hash} actual={actual_hash}"
            )

        issues: list[RequirementUnitIssue] = []
        chunks: list[RequirementExtractionChunk] = []
        coverage: list[RequirementChunkCoverage] = []
        for section in sorted(sections, key=lambda item: (item.source_ref, item.heading, item.content)):
            section_chunks = build_requirement_chunks(
                section,
                max_chars=self.max_chunk_chars,
                overlap_chars=self.chunk_overlap_chars,
            )
            if not section_chunks:
                issues.append(RequirementUnitIssue(source_ref=section.source_ref, code="empty_section"))
                empty_hash = hashlib.sha256(b"").hexdigest()
                coverage.append(
                    RequirementChunkCoverage(
                        coverage_id=build_requirement_coverage_id(
                            document_content_hash=document_content_hash,
                            source_ref=section.source_ref,
                            chunk_index=1,
                            content_hash=empty_hash,
                        ),
                        source_ref=section.source_ref,
                        heading=section.heading,
                        section_kind=section.section_kind,
                        chunk_index=1,
                        chunk_count=1,
                        content_hash=empty_hash,
                        disposition="empty_section",
                        reason="章节正文为空。",
                    )
                )
                continue
            if section.section_kind not in self.eligible_section_kinds:
                issues.append(
                    RequirementUnitIssue(
                        source_ref=section.source_ref,
                        code="section_not_induction_eligible",
                        details={"section_kind": section.section_kind},
                    )
                )
                coverage.extend(
                    RequirementChunkCoverage(
                        coverage_id=build_requirement_coverage_id(
                            document_content_hash=document_content_hash,
                            source_ref=chunk.source_ref,
                            chunk_index=chunk.chunk_index,
                            content_hash=chunk.content_hash,
                        ),
                        source_ref=chunk.source_ref,
                        heading=chunk.heading,
                        section_kind=chunk.section_kind,
                        chunk_index=chunk.chunk_index,
                        chunk_count=chunk.chunk_count,
                        content_hash=chunk.content_hash,
                        disposition="excluded_non_spec",
                        reason=f"section_kind={section.section_kind} 不参与当前 taxonomy induction。",
                    )
                    for chunk in section_chunks
                )
                continue
            chunks.extend(section_chunks)

        semaphore = asyncio.Semaphore(self.concurrency)

        async def extract_chunk(
            chunk: RequirementExtractionChunk,
        ) -> tuple[RequirementExtractionChunk, RequirementUnitDraftBatch | None, Exception | None]:
            try:
                async with semaphore:
                    raw_batch = await extractor(chunk)
                batch = RequirementUnitDraftBatch.model_validate(raw_batch)
                return chunk, batch, None
            except Exception as exc:  # noqa: BLE001 - 外部模型失败必须转为显式拒识证据
                return chunk, None, exc

        extracted = await asyncio.gather(*(extract_chunk(chunk) for chunk in chunks))
        candidate_units: list[RequirementUnit] = []
        chunk_batches: dict[str, RequirementUnitDraftBatch] = {}
        chunk_errors: dict[str, Exception] = {}
        chunk_unit_ids: dict[str, list[str]] = {}
        for chunk, batch, error in extracted:
            coverage_id = build_requirement_coverage_id(
                document_content_hash=document_content_hash,
                source_ref=chunk.source_ref,
                chunk_index=chunk.chunk_index,
                content_hash=chunk.content_hash,
            )
            if error is not None:
                chunk_errors[coverage_id] = error
                issues.append(
                    RequirementUnitIssue(
                        source_ref=chunk.source_ref,
                        chunk_index=chunk.chunk_index,
                        code="extractor_failed",
                        details={"error_type": type(error).__name__},
                    )
                )
                continue
            assert batch is not None
            chunk_batches[coverage_id] = batch
            for draft in batch.units:
                unit = self._ground_draft(
                    draft=draft,
                    chunk=chunk,
                    system_id=system_id,
                    document_id=document_id,
                    document_content_hash=document_content_hash,
                    document_snapshot=document_snapshot,
                    issues=issues,
                )
                candidate_units.append(unit)
                chunk_unit_ids.setdefault(coverage_id, []).append(unit.unit_id)

        units = self._deduplicate(candidate_units, issues)
        semantic_verifications: list[RequirementUnitSemanticVerification] = []
        if verifier is not None and units:
            verified_units: list[RequirementUnit] = []
            for start in range(0, len(units), 20):
                batch_units = units[start : start + 20]
                expected_ids = {unit.unit_id for unit in batch_units}
                try:
                    raw_verifications = await verifier(batch_units)
                    verification_batch = RequirementUnitVerificationBatch.model_validate(raw_verifications)
                    actual_ids = [item.requirement_unit_id for item in verification_batch.verifications]
                    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
                        raise ValueError("requirement_semantic_verification_coverage_invalid")
                except Exception as exc:  # noqa: BLE001 - verifier 失败必须逐 unit fail closed
                    for unit in batch_units:
                        issues.append(
                            RequirementUnitIssue(
                                source_ref=unit.source_ref,
                                code="semantic_verifier_failed",
                                details={"unit_id": unit.unit_id, "error_type": type(exc).__name__},
                            )
                        )
                        semantic_verifications.append(
                            RequirementUnitSemanticVerification(
                                requirement_unit_id=unit.unit_id,
                                verdict="not_entailed",
                                reason="独立语义核验失败，按不支持处理。",
                            )
                        )
                        verified_units.append(unit.model_copy(update={"scope_status": "unsupported"}))
                    continue

                by_id = {item.requirement_unit_id: item for item in verification_batch.verifications}
                for unit in batch_units:
                    verification = by_id[unit.unit_id]
                    semantic_verifications.append(verification)
                    if verification.verdict == "not_entailed":
                        issues.append(
                            RequirementUnitIssue(
                                source_ref=unit.source_ref,
                                code="semantic_evidence_not_entailed",
                                details={"unit_id": unit.unit_id},
                            )
                        )
                        unit = unit.model_copy(update={"scope_status": "unsupported"})
                    verified_units.append(unit)
            units = verified_units

        final_unit_ids = {unit.unit_id for unit in units}
        chunks_by_coverage_id = {
            build_requirement_coverage_id(
                document_content_hash=document_content_hash,
                source_ref=chunk.source_ref,
                chunk_index=chunk.chunk_index,
                content_hash=chunk.content_hash,
            ): chunk
            for chunk in chunks
        }
        for coverage_id, chunk in sorted(chunks_by_coverage_id.items()):
            if coverage_id in chunk_errors:
                coverage.append(
                    RequirementChunkCoverage(
                        coverage_id=coverage_id,
                        source_ref=chunk.source_ref,
                        heading=chunk.heading,
                        section_kind=chunk.section_kind,
                        chunk_index=chunk.chunk_index,
                        chunk_count=chunk.chunk_count,
                        content_hash=chunk.content_hash,
                        disposition="failed",
                        reason=f"extractor_failed:{type(chunk_errors[coverage_id]).__name__}",
                    )
                )
                continue
            batch = chunk_batches[coverage_id]
            accepted_ids = sorted(set(chunk_unit_ids.get(coverage_id, [])) & final_unit_ids)
            if batch.disposition == "no_requirement":
                coverage.append(
                    RequirementChunkCoverage(
                        coverage_id=coverage_id,
                        source_ref=chunk.source_ref,
                        heading=chunk.heading,
                        section_kind=chunk.section_kind,
                        chunk_index=chunk.chunk_index,
                        chunk_count=chunk.chunk_count,
                        content_hash=chunk.content_hash,
                        disposition="no_requirement",
                        reason=batch.reason,
                    )
                )
            elif accepted_ids:
                coverage.append(
                    RequirementChunkCoverage(
                        coverage_id=coverage_id,
                        source_ref=chunk.source_ref,
                        heading=chunk.heading,
                        section_kind=chunk.section_kind,
                        chunk_index=chunk.chunk_index,
                        chunk_count=chunk.chunk_count,
                        content_hash=chunk.content_hash,
                        disposition="requirements_extracted",
                        requirement_unit_ids=accepted_ids,
                    )
                )
            else:
                coverage.append(
                    RequirementChunkCoverage(
                        coverage_id=coverage_id,
                        source_ref=chunk.source_ref,
                        heading=chunk.heading,
                        section_kind=chunk.section_kind,
                        chunk_index=chunk.chunk_index,
                        chunk_count=chunk.chunk_count,
                        content_hash=chunk.content_hash,
                        disposition="failed",
                        reason="提取结果因冲突或无效证据未形成可用 unit。",
                    )
                )

        input_hash = _extraction_input_hash(
            system_id=system_id,
            document_id=document_id,
            document_content_hash=document_content_hash,
            sections=sections,
            max_chunk_chars=self.max_chunk_chars,
            chunk_overlap_chars=self.chunk_overlap_chars,
            eligible_section_kinds=self.eligible_section_kinds,
            prompt_revision=prompt_revision,
            model_revision=model_revision,
            verifier_prompt_revision=verifier_prompt_revision,
            verifier_model_revision=verifier_model_revision,
        )
        return RequirementUnitExtractionResult(
            document_id=document_id,
            document_content_hash=document_content_hash,
            input_hash=input_hash,
            prompt_revision=prompt_revision,
            model_revision=model_revision,
            verifier_prompt_revision=verifier_prompt_revision,
            verifier_model_revision=verifier_model_revision,
            chunk_count=len(coverage),
            units=sorted(units, key=lambda unit: (unit.source_ref, unit.structural_key, unit.unit_id)),
            coverage=sorted(
                coverage,
                key=lambda item: (item.source_ref, item.chunk_index, item.coverage_id),
            ),
            semantic_verifications=sorted(
                semantic_verifications,
                key=lambda item: item.requirement_unit_id,
            ),
            issues=sorted(
                issues,
                key=lambda issue: (
                    issue.source_ref,
                    issue.chunk_index or 0,
                    issue.code,
                    _canonical_details(issue.details),
                ),
            ),
        )

    @staticmethod
    def _ground_draft(
        *,
        draft: RequirementUnitDraft,
        chunk: RequirementExtractionChunk,
        system_id: UUID,
        document_id: UUID,
        document_content_hash: str,
        document_snapshot: str,
        issues: list[RequirementUnitIssue],
    ) -> RequirementUnit:
        quote_grounded = draft.source_quote in chunk.content and draft.source_quote in document_snapshot
        scope_status: RequirementUnitScopeStatus = (
            draft.scope_status if quote_grounded and chunk.section_kind == "spec" else "unsupported"
        )
        if not quote_grounded:
            issues.append(
                RequirementUnitIssue(
                    source_ref=chunk.source_ref,
                    chunk_index=chunk.chunk_index,
                    code="source_quote_not_grounded",
                    details={
                        "quote_hash": build_source_quote_hash(draft.source_quote),
                        "chunk_hash": chunk.content_hash,
                    },
                )
            )

        return RequirementUnit(
            unit_id=build_requirement_unit_id(
                document_content_hash=document_content_hash,
                source_ref=chunk.source_ref,
                statement=draft.statement,
            ),
            system_id=system_id,
            document_id=document_id,
            document_content_hash=document_content_hash,
            source_ref=chunk.source_ref,
            source_quote=draft.source_quote,
            source_quote_hash=build_source_quote_hash(draft.source_quote),
            structural_key=draft.structural_key,
            title=draft.title,
            statement=draft.statement,
            observable_outcome=draft.observable_outcome,
            scope_status=scope_status,
        )

    @staticmethod
    def _deduplicate(
        units: list[RequirementUnit],
        issues: list[RequirementUnitIssue],
    ) -> list[RequirementUnit]:
        grouped: dict[str, list[RequirementUnit]] = {}
        for unit in units:
            grouped.setdefault(unit.unit_id, []).append(unit)

        deduplicated: list[RequirementUnit] = []
        for unit_id, duplicates in sorted(grouped.items()):
            payloads = {
                json.dumps(
                    unit.model_dump(mode="json", exclude={"title"}),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for unit in duplicates
            }
            if len(payloads) == 1:
                deduplicated.append(min(duplicates, key=lambda unit: (unit.title, unit.unit_id)))
                continue
            issues.append(
                RequirementUnitIssue(
                    source_ref=duplicates[0].source_ref,
                    code="duplicate_unit_payload_conflict",
                    details={"unit_id": unit_id, "variant_count": len(payloads)},
                )
            )
        return deduplicated


def _canonical_details(details: dict[str, str | int]) -> str:
    return json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _complete_windows(content: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    if len(content) <= max_chars:
        return [content]

    windows: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + max_chars, len(content))
        windows.append(content[start:end])
        if end == len(content):
            break

        next_start = end - overlap_chars
        remaining_after_next_window = len(content) - (next_start + max_chars)
        if 0 < remaining_after_next_window <= overlap_chars:
            next_start = len(content) - max_chars
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return windows


def _extraction_input_hash(
    *,
    system_id: UUID,
    document_id: UUID,
    document_content_hash: str,
    sections: list[SectionExtract],
    max_chunk_chars: int,
    chunk_overlap_chars: int,
    eligible_section_kinds: frozenset[SectionKind],
    prompt_revision: str,
    model_revision: str,
    verifier_prompt_revision: str | None,
    verifier_model_revision: str | None,
) -> str:
    section_payloads = [
        {
            "source_ref": section.source_ref,
            "heading": section.heading,
            "section_kind": section.section_kind,
            "content_hash": hashlib.sha256(section.content.encode("utf-8")).hexdigest(),
        }
        for section in sections
    ]
    payload = {
        "system_id": str(system_id),
        "document_id": str(document_id),
        "document_content_hash": document_content_hash,
        "sections": sorted(
            section_payloads,
            key=lambda item: (
                item["source_ref"],
                item["heading"],
                item["section_kind"],
                item["content_hash"],
            ),
        ),
        "max_chunk_chars": max_chunk_chars,
        "chunk_overlap_chars": chunk_overlap_chars,
        "eligible_section_kinds": sorted(eligible_section_kinds),
        "prompt_revision": prompt_revision,
        "model_revision": model_revision,
        "verifier_prompt_revision": verifier_prompt_revision,
        "verifier_model_revision": verifier_model_revision,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
