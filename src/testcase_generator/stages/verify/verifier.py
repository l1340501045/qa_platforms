"""verify 关卡内核 — 与 PipelineState 解耦，可被流水线节点与离线验证脚本共用。

按功能点分片 + 案数子批并发核验（复用 review 已验证的防超窗模式），单批失败隔离。
verdict → bucket 在代码里确定性映射，不靠 LLM 自由发挥。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List

from pydantic import BaseModel, Field

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.test_case import (
    Bucket,
    CaseVerification,
    CrossSectionConflictRef,
    Verdict,
)
from src.testcase_generator.services.llm_client import get_llm_client
from src.testcase_generator.stages.verify.rubric import (
    CROSS_SECTION_CONFLICT_INSTRUCTION,
    VERIFY_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# verdict → bucket 确定性映射（与 plan 约定：isolate）
_VERDICT_BUCKET: dict[str, Bucket] = {
    "grounded": "main",
    "conflict": "to_fix",
    "ungrounded": "needs_spec",
    "undefined": "needs_spec",
}

# 单批最多核验的用例条数（控制单次输出长度，规避网关超时；不减少总数，分批聚合）
MAX_CASES_PER_BATCH = 15


@dataclass
class VerifyCase:
    """核验输入：一条用例的可核验信息（与 ORM/Pydantic 解耦）"""

    case_id: str  # 稳定标识，用于把 verdict 映射回原用例（可用 DB id 或 TC-id）
    feature_id: str
    title: str
    steps: list[dict] = field(default_factory=list)  # {action,input_data,expected_result,source_quote?}
    expected_results: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    provenance_excerpt: str | None = None


@dataclass
class PrdSection:
    """供核验对照的 PRD 章节原文"""

    heading: str
    content: str
    source_ref: str
    section_kind: str = "spec"


# ─── LLM 输出 schema ─────────────────────────────────────────────────────────


class _ConflictRef(BaseModel):
    ref_a: str = ""
    quote_a: str = ""
    ref_b: str = ""
    quote_b: str = ""


class _CaseVerdict(BaseModel):
    case_id: str = Field(description="回填输入中的 case_id")
    verdict: str = Field(description="grounded / conflict / undefined / ungrounded")
    rationale: str = Field(default="", description="判定理由，一句话")
    prd_evidence: str | None = Field(default=None, description="PRD 原文摘录（直接引用）")
    unsupported_assertions: List[str] = Field(default_factory=list, description="无支撑/冲突的具体断言")
    cross_section_conflict: bool = Field(default=False, description="PRD 条款间实质互斥")
    conflicting_refs: List[_ConflictRef] = Field(default_factory=list, description="互斥条款对")


class _VerifyLLMOutput(BaseModel):
    verdicts: List[_CaseVerdict] = Field(description="对每条用例的核验结论")


def _normalize_verdict(raw: str) -> Verdict:
    v = (raw or "").strip().lower()
    if v in ("grounded", "conflict", "undefined", "ungrounded"):
        return v  # type: ignore[return-value]
    return "ungrounded"  # 无法识别时从严（不放进主集）


def _case_payload(c: VerifyCase) -> dict:
    return {
        "case_id": c.case_id,
        "feature_id": c.feature_id,
        "title": c.title,
        "preconditions": c.preconditions,
        "steps": [
            {
                "action": s.get("action", ""),
                "input_data": s.get("input_data", ""),
                "expected_result": s.get("expected_result", ""),
                **({"claimed_source_quote": s["source_quote"]} if s.get("source_quote") else {}),
            }
            for s in c.steps
        ],
        "expected_results": c.expected_results,
        "claimed_provenance_excerpt": c.provenance_excerpt,
    }


def _sections_payload(sections: list[PrdSection]) -> list[dict]:
    return [
        {"heading": s.heading, "source_ref": s.source_ref, "section_kind": s.section_kind, "content": s.content}
        for s in sections
    ]


def _split(items: list, size: int) -> list[list]:
    if len(items) <= size:
        return [items] if items else []
    return [items[i : i + size] for i in range(0, len(items), size)]


async def verify_cases(
    cases: list[VerifyCase],
    prd_sections_by_feature: dict[str, list[PrdSection]],
    *,
    max_cases_per_batch: int = MAX_CASES_PER_BATCH,
) -> dict[str, CaseVerification]:
    """对一批用例逐条核验，返回 {case_id: CaseVerification}。

    - 按 feature 分片，每片只对照该 feature 的 PRD 章节原文（防超窗、对照精准）。
    - 片内再按案数子批；批间并发；单批失败该批用例标 unverified（不污染其它批）。
    """
    by_feature: dict[str, list[VerifyCase]] = defaultdict(list)
    for c in cases:
        by_feature[c.feature_id].append(c)

    system_prompt = VERIFY_SYSTEM_PROMPT
    if settings.verify_cross_section_conflict_enabled:
        system_prompt += CROSS_SECTION_CONFLICT_INSTRUCTION

    semaphore = asyncio.Semaphore(settings.llm_concurrency)
    results: dict[str, CaseVerification] = {}

    async def _verify_batch(feature_id: str, batch: list[VerifyCase]) -> dict[str, CaseVerification]:
        sections = prd_sections_by_feature.get(feature_id, [])
        user_content = json.dumps(
            {
                "prd_sections": _sections_payload(sections),
                "test_cases": [_case_payload(c) for c in batch],
            },
            ensure_ascii=False,
            indent=2,
        )
        async with semaphore:
            try:
                out = await get_llm_client().generate_structured(
                    system_prompt=system_prompt,
                    user_content=user_content,
                    output_schema=_VerifyLLMOutput,
                    temperature=0.1,
                    model=settings.llm_verify_model or None,
                )
            except Exception as e:  # noqa: BLE001 — 单批失败隔离
                logger.error("verify 失败 (feature=%s, n=%d): %s", feature_id, len(batch), e)
                return {c.case_id: CaseVerification(verdict="unverified", bucket="main") for c in batch}

        by_id = {v.case_id: v for v in out.verdicts}
        batch_result: dict[str, CaseVerification] = {}
        for c in batch:
            v = by_id.get(c.case_id)
            if v is None:
                # LLM 漏判 → 从严标 unverified，留主集但提示需人工看
                batch_result[c.case_id] = CaseVerification(
                    verdict="unverified", bucket="main", rationale="LLM 未返回该用例核验结论"
                )
                continue
            verdict = _normalize_verdict(v.verdict)
            batch_result[c.case_id] = CaseVerification(
                verdict=verdict,
                bucket=_VERDICT_BUCKET.get(verdict, "needs_spec"),
                rationale=v.rationale,
                prd_evidence=v.prd_evidence,
                unsupported_assertions=v.unsupported_assertions,
                cross_section_conflict=v.cross_section_conflict,
                conflicting_refs=[
                    CrossSectionConflictRef(ref_a=r.ref_a, quote_a=r.quote_a, ref_b=r.ref_b, quote_b=r.quote_b)
                    for r in v.conflicting_refs
                ],
            )
        return batch_result

    tasks = []
    for feature_id, fcases in by_feature.items():
        for batch in _split(fcases, max_cases_per_batch):
            tasks.append(_verify_batch(feature_id, batch))

    logger.info("verify: %d 个功能点拆成 %d 批核验, 并发度=%d", len(by_feature), len(tasks), settings.llm_concurrency)
    batch_results = await asyncio.gather(*tasks)
    for br in batch_results:
        results.update(br)
    return results


def summarize(verifications: dict[str, CaseVerification]) -> dict:
    """聚合核验结果分布 + PRD 矛盾清单。"""
    by_verdict: dict[str, int] = defaultdict(int)
    by_bucket: dict[str, int] = defaultdict(int)
    conflict_pairs: dict[tuple, dict] = {}
    for v in verifications.values():
        by_verdict[v.verdict] += 1
        by_bucket[v.bucket] += 1
        if v.cross_section_conflict:
            for r in v.conflicting_refs:
                key = tuple(sorted([(r.ref_a, r.quote_a), (r.ref_b, r.quote_b)]))
                slot = conflict_pairs.setdefault(key, {
                    "ref_a": r.ref_a, "quote_a": r.quote_a,
                    "ref_b": r.ref_b, "quote_b": r.quote_b, "case_count": 0,
                })
                slot["case_count"] += 1
    return {
        "total": len(verifications),
        "by_verdict": dict(by_verdict),
        "by_bucket": dict(by_bucket),
        "cross_section_conflicts": sum(1 for v in verifications.values() if v.cross_section_conflict),
        "prd_conflict_list": list(conflict_pairs.values()),
    }
