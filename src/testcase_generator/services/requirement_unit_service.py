"""从带来源锚点的 PRD 章节提取可回放的原子需求单元。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.testcase_generator.schemas.parsed_context import SectionExtract, SectionKind
from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)

RequirementUnitScopeStatus = Literal["atomic", "wide", "unsupported", "conflicted"]
REQUIREMENT_UNIT_PROMPT_REVISION = "requirement-unit-v1"

_REQUIREMENT_UNIT_SYSTEM_PROMPT = """你是需求事实原子化器，只处理当前给出的 PRD 章节片段。
规则：
1. 只引用当前输入中的原文，不得使用测试用例标题、常识或其他章节补全事实。
2. 每个 unit 只表达一个可独立观察的业务结果；能拆分的联合描述必须拆成多个 unit。
3. source_quote 必须逐字摘自当前 content，不能改写、拼接或省略关键条件。
4. 无法可靠拆分的联合约束标为 wide；来源不足标为 unsupported；原文明示冲突标为 conflicted。
5. structural_key 只描述稳定业务能力，不使用章节编号或测试用例编号。
6. 不生成目录节点，不推断实现机制，不输出当前 schema 以外字段。"""


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

    units: list[RequirementUnitDraft] = Field(default_factory=list, max_length=50)


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
    ]
    details: dict[str, str | int] = Field(default_factory=dict)


class RequirementUnitExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    document_id: UUID
    document_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_revision: str = Field(min_length=1, max_length=255)
    model_revision: str = Field(min_length=1, max_length=255)
    chunk_count: int = Field(ge=0)
    units: list[RequirementUnit] = Field(default_factory=list)
    issues: list[RequirementUnitIssue] = Field(default_factory=list)


RequirementUnitExtractor = Callable[[RequirementExtractionChunk], Awaitable[object]]
StructuredGenerateFn = Callable[..., Awaitable[RequirementUnitDraftBatch]]


@dataclass(frozen=True)
class RequirementUnitExtractorBinding:
    extractor: RequirementUnitExtractor
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
    ) -> RequirementUnitExtractionResult:
        prompt_revision = prompt_revision.strip()
        model_revision = model_revision.strip()
        if not prompt_revision or not model_revision:
            raise ValueError("requirement_extractor_revision_required")
        actual_hash = hashlib.sha256(document_snapshot.encode("utf-8")).hexdigest()
        if actual_hash != document_content_hash:
            raise DocumentSnapshotMismatchError(
                f"document_snapshot_hash_mismatch: expected={document_content_hash} actual={actual_hash}"
            )

        issues: list[RequirementUnitIssue] = []
        chunks: list[RequirementExtractionChunk] = []
        for section in sorted(sections, key=lambda item: (item.source_ref, item.heading, item.content)):
            if section.section_kind not in self.eligible_section_kinds:
                issues.append(
                    RequirementUnitIssue(
                        source_ref=section.source_ref,
                        code="section_not_induction_eligible",
                        details={"section_kind": section.section_kind},
                    )
                )
                continue
            section_chunks = build_requirement_chunks(
                section,
                max_chars=self.max_chunk_chars,
                overlap_chars=self.chunk_overlap_chars,
            )
            if not section_chunks:
                issues.append(RequirementUnitIssue(source_ref=section.source_ref, code="empty_section"))
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
        for chunk, batch, error in extracted:
            if error is not None:
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
            for draft in batch.units:
                candidate_units.append(
                    self._ground_draft(
                        draft=draft,
                        chunk=chunk,
                        system_id=system_id,
                        document_id=document_id,
                        document_content_hash=document_content_hash,
                        document_snapshot=document_snapshot,
                        issues=issues,
                    )
                )

        units = self._deduplicate(candidate_units, issues)
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
        )
        return RequirementUnitExtractionResult(
            document_id=document_id,
            document_content_hash=document_content_hash,
            input_hash=input_hash,
            prompt_revision=prompt_revision,
            model_revision=model_revision,
            chunk_count=len(chunks),
            units=sorted(units, key=lambda unit: (unit.source_ref, unit.structural_key, unit.unit_id)),
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
        scope_status: RequirementUnitScopeStatus = draft.scope_status if quote_grounded else "unsupported"
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
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
