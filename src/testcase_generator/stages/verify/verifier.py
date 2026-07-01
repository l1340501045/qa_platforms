"""verify 关卡内核 — 与 PipelineState 解耦，可被流水线节点与离线验证脚本共用。

按功能点分片 + 案数子批并发核验（复用 review 已验证的防超窗模式），单批失败隔离。
verdict → bucket 在代码里确定性映射，不靠 LLM 自由发挥。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
    CONFLICT_ENTITY_GATE_INSTRUCTION,
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

_RECONCILE_STRICTNESS: dict[str, int] = {
    "grounded": 0,
    "ungrounded": 1,
    "undefined": 2,
    "conflict": 3,
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
    # 同实体门控（conflict_entity_gate）：判 conflict 时须结构化输出双方对象 + 是否同一实体。
    # same_entity 默认 True：未输出 / 不开门控时不误撤真 conflict（保守）。
    conflict_subject_case: str = Field(default="", description="用例断言所约束的对象/字段")
    conflict_subject_prd: str = Field(default="", description="PRD 反驳条款所约束的对象/字段")
    same_entity: bool = Field(default=True, description="二者是否同一实体（True=同实体，不撤）")


class _VerifyLLMOutput(BaseModel):
    verdicts: List[_CaseVerdict] = Field(description="对每条用例的核验结论")


def _normalize_verdict(raw: str) -> Verdict:
    v = (raw or "").strip().lower()
    if v in ("grounded", "conflict", "undefined", "ungrounded"):
        return v  # type: ignore[return-value]
    return "ungrounded"  # 无法识别时从严（不放进主集）


# ─── 同实体门控 · 词法兜底（字符集 Jaccard）─────────────────────────────────
# 归一化：保留中日韩与字母（仿 dedup/clustering._normalize），去标点/数字/空白后取【字符集】。
# 注意：字符集（set）而非 bigram/公共 token——"监测链接"与"投放链接"共享"链接"二字，
# 但 Jaccard=|{链,接}|/|{监,测,链,接,投,放}|=2/6≈0.33<0.5 → 判不同实体（核心护栏，
# 不可退化为"有无公共 token"，否则会把不同实体误判同实体、门控失效）。
_ENTITY_KEEP = re.compile(r"[一-鿿a-zA-Z]+")
_TITLE_KEEP = re.compile(r"[一-鿿a-zA-Z0-9]+")


def _normalize_entity(s: str) -> str:
    return "".join(_ENTITY_KEEP.findall((s or "").lower()))


def _same_entity(a: str, b: str, *, threshold: float | None = None) -> bool:
    """字符集 Jaccard 判两 subject 是否同一实体。

    - Jaccard = |A∩B| / |A∪B|；>= threshold → True（同实体，不撤）；< threshold → False（不同实体）。
    - 任一归一化后为空串 → 返回 True（无法判定、保守不撤，防误伤真 conflict）。
    - 阈值默认取 settings.conflict_entity_jaccard_threshold。
    """
    sa, sb = _normalize_entity(a), _normalize_entity(b)
    if not sa or not sb:
        return True
    set_a, set_b = set(sa), set(sb)
    union = set_a | set_b
    if not union:
        return True
    jaccard = len(set_a & set_b) / len(union)
    thr = settings.conflict_entity_jaccard_threshold if threshold is None else threshold
    return jaccard >= thr


def _normalize_title(s: str) -> str:
    return "".join(_TITLE_KEEP.findall((s or "").lower()))


def _choose_reconciled_verdict(verdicts: list[str]) -> Verdict:
    counts = Counter(verdicts)
    max_count = max(counts.values())
    tied = [verdict for verdict, count in counts.items() if count == max_count]
    return max(tied, key=lambda verdict: _RECONCILE_STRICTNESS.get(verdict, -1))  # type: ignore[return-value]


def reconcile_verdicts(
    results: dict[str, CaseVerification],
    cases: list[VerifyCase],
    *,
    sim: float | None = None,
) -> dict[str, CaseVerification]:
    """同 feature 高相似用例 verdict 判后一致化。"""
    threshold = settings.reconcile_sim if sim is None else sim
    reconciled = dict(results)
    cases_by_feature: dict[str, list[VerifyCase]] = defaultdict(list)
    for c in cases:
        if c.feature_id and c.case_id in results and results[c.case_id].verdict in _RECONCILE_STRICTNESS:
            cases_by_feature[c.feature_id].append(c)

    for feature_cases in cases_by_feature.values():
        if len(feature_cases) < 2:
            continue

        parent = {c.case_id: c.case_id for c in feature_cases}

        def find(case_id: str) -> str:
            while parent[case_id] != case_id:
                parent[case_id] = parent[parent[case_id]]
                case_id = parent[case_id]
            return case_id

        def union(a: str, b: str) -> None:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_b] = root_a

        normalized_titles = {c.case_id: _normalize_title(c.title) for c in feature_cases}
        for idx, left in enumerate(feature_cases):
            for right in feature_cases[idx + 1 :]:
                title_left = normalized_titles[left.case_id]
                title_right = normalized_titles[right.case_id]
                if not title_left or not title_right:
                    continue
                if SequenceMatcher(None, title_left, title_right).ratio() >= threshold:
                    union(left.case_id, right.case_id)

        clusters: dict[str, list[str]] = defaultdict(list)
        for c in feature_cases:
            clusters[find(c.case_id)].append(c.case_id)

        for case_ids in clusters.values():
            if len(case_ids) < 2:
                continue

            cluster_results = [reconciled[case_id] for case_id in case_ids]
            has_mismatch = any(item.conflict_entity_mismatch for item in cluster_results)
            verdicts = [item.verdict for item in cluster_results if item.verdict in _RECONCILE_STRICTNESS]
            if has_mismatch:
                verdicts = [verdict for verdict in verdicts if verdict != "conflict"]
                if not verdicts:
                    verdicts = ["ungrounded"]
            if not verdicts:
                continue

            verdict = _choose_reconciled_verdict(verdicts)
            bucket = _VERDICT_BUCKET.get(verdict, "needs_spec")
            for case_id in case_ids:
                original = reconciled[case_id]
                rationale = original.rationale or ""
                rationale = f"{rationale}（同构一致化：簇内多数 → {verdict}）"
                reconciled[case_id] = original.model_copy(
                    update={
                        "verdict": verdict,
                        "bucket": bucket,
                        "rationale": rationale,
                        "conflict_entity_mismatch": original.conflict_entity_mismatch or has_mismatch,
                    }
                )

    return reconciled


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
    if settings.conflict_entity_gate_enabled:
        system_prompt += CONFLICT_ENTITY_GATE_INSTRUCTION
    if settings.verify_cross_section_conflict_enabled:
        system_prompt += CROSS_SECTION_CONFLICT_INSTRUCTION

    semaphore = asyncio.Semaphore(settings.llm_concurrency)
    results: dict[str, CaseVerification] = {}

    async def _verify_batch(feature_id: str, batch: list[VerifyCase]) -> dict[str, CaseVerification]:
        sections = prd_sections_by_feature.get(feature_id, [])

        def _build_user_content(batch_cases: list[VerifyCase]) -> str:
            return json.dumps(
                {
                    "prd_sections": _sections_payload(sections),
                    "test_cases": [_case_payload(c) for c in batch_cases],
                },
                ensure_ascii=False,
                indent=2,
            )

        async with semaphore:
            client = get_llm_client()

            async def _call_llm(batch_cases: list[VerifyCase]) -> _VerifyLLMOutput:
                return await client.generate_structured(
                    system_prompt=system_prompt,
                    user_content=_build_user_content(batch_cases),
                    output_schema=_VerifyLLMOutput,
                    temperature=0.1,
                    model=settings.llm_verify_model or None,
                )

            try:
                out = await _call_llm(batch)
            except Exception as e:  # noqa: BLE001 — 单批失败隔离
                logger.error("verify 失败 (feature=%s, n=%d): %s", feature_id, len(batch), e)
                return {c.case_id: CaseVerification(verdict="unverified", bucket="main") for c in batch}

        by_id = {v.case_id: v for v in out.verdicts}
        if settings.conflict_revote_enabled and settings.revote_n > 1:
            conflict_cases = [
                c
                for c in batch
                if (initial := by_id.get(c.case_id)) is not None and _normalize_verdict(initial.verdict) == "conflict"
            ]
            if conflict_cases:
                votes: dict[str, list[_CaseVerdict]] = {c.case_id: [by_id[c.case_id]] for c in conflict_cases}
                async with semaphore:
                    client = get_llm_client()

                    async def _revote_llm() -> _VerifyLLMOutput:
                        return await client.generate_structured(
                            system_prompt=system_prompt,
                            user_content=_build_user_content(conflict_cases),
                            output_schema=_VerifyLLMOutput,
                            temperature=0.1,
                            model=settings.llm_verify_model or None,
                        )

                    for _ in range(settings.revote_n - 1):
                        try:
                            revote_out = await _revote_llm()
                        except Exception as e:  # noqa: BLE001 — 复判失败不放大为整批失败
                            logger.warning(
                                "verify conflict 复判失败 (feature=%s, n=%d): %s",
                                feature_id,
                                len(conflict_cases),
                                e,
                            )
                            continue
                        for verdict in revote_out.verdicts:
                            if verdict.case_id in votes:
                                votes[verdict.case_id].append(verdict)

                for case_id, case_votes in votes.items():
                    verdict = _choose_reconciled_verdict([_normalize_verdict(v.verdict) for v in case_votes])
                    chosen = next(
                        (v for v in reversed(case_votes) if _normalize_verdict(v.verdict) == verdict),
                        case_votes[-1],
                    )
                    by_id[case_id] = chosen.model_copy(update={"verdict": verdict})
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
            _refs = [
                CrossSectionConflictRef(ref_a=r.ref_a, quote_a=r.quote_a, ref_b=r.ref_b, quote_b=r.quote_b)
                for r in v.conflicting_refs
            ]
            _conflict = bool(v.cross_section_conflict and _refs)

            # ── 同实体门控：治概念混淆型假 conflict ────────────────────────────
            # 对 verdict=conflict 的用例：仅当 LLM 明确判 same_entity=False 时撤销 conflict、
            # 降级 ungrounded（needs_spec）+ conflict_entity_mismatch=True。
            # 词法 _same_entity 作为 same_entity=False 的佐证（写入 rationale），但【不单独
            # 触发降级】——尊重 LLM 的明确同实体判断（same_entity=True），防词法把"同实体但
            # 措辞分歧大"的真 conflict 误降级（如"标题字数上限" vs "字数" Jaccard 低却同实体）。
            # 这样真 conflict（同实体）same_entity=True → 不降级；假 conflict（不同实体）
            # same_entity=False → 降级，词法兜底仅作辅助标注。
            _subject_case = v.conflict_subject_case or ""
            _subject_prd = v.conflict_subject_prd or ""
            _entity_mismatch = False
            _lexical_note = ""
            if settings.conflict_entity_gate_enabled and verdict == "conflict":
                if v.same_entity is False:
                    verdict = "ungrounded"
                    _entity_mismatch = True
                    # 词法佐证：subject 非空时算 Jaccard，写入 rationale 供人工复核
                    if _subject_case and _subject_prd:
                        _lexical_same = _same_entity(_subject_case, _subject_prd)
                        _lexical_note = f"词法 Jaccard 判定{'同' if _lexical_same else '不同'}实体（佐证 LLM 判定）；"

            _rationale = v.rationale
            if _entity_mismatch:
                _rationale = (
                    f"原 conflict 因用例对象「{_subject_case}」与 PRD 反驳条款对象「{_subject_prd}」"
                    f"非同一实体（概念混淆假矛盾）撤销，降级待人工确认是否其实 grounded。"
                    f"{_lexical_note}原判理由：{_rationale}"
                )

            batch_result[c.case_id] = CaseVerification(
                verdict=verdict,
                bucket=_VERDICT_BUCKET.get(verdict, "needs_spec"),
                rationale=_rationale,
                prd_evidence=v.prd_evidence,
                unsupported_assertions=v.unsupported_assertions,
                cross_section_conflict=_conflict,
                conflicting_refs=_refs,
                conflict_subject_case=_subject_case,
                conflict_subject_prd=_subject_prd,
                conflict_entity_mismatch=_entity_mismatch,
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
    if settings.verdict_reconcile_enabled:
        results = reconcile_verdicts(results, cases)
    return results


def summarize(verifications: dict[str, CaseVerification]) -> dict:
    """聚合核验结果分布 + PRD 矛盾清单。"""
    by_verdict: dict[str, int] = defaultdict(int)
    by_bucket: dict[str, int] = defaultdict(int)
    conflict_pairs: dict[tuple, dict] = {}
    n_conflict_cases = 0
    for case_id, v in verifications.items():
        by_verdict[v.verdict] += 1
        by_bucket[v.bucket] += 1
        if v.cross_section_conflict:
            n_conflict_cases += 1
            seen_keys_this_case: set[tuple] = set()
            for r in v.conflicting_refs:
                key = tuple(sorted([(r.ref_a, r.quote_a), (r.ref_b, r.quote_b)]))
                if key in seen_keys_this_case:
                    continue
                seen_keys_this_case.add(key)
                slot = conflict_pairs.setdefault(
                    key,
                    {
                        "ref_a": r.ref_a,
                        "quote_a": r.quote_a,
                        "ref_b": r.ref_b,
                        "quote_b": r.quote_b,
                        "case_count": 0,
                    },
                )
                slot["case_count"] += 1
    return {
        "total": len(verifications),
        "by_verdict": dict(by_verdict),
        "by_bucket": dict(by_bucket),
        "cross_section_conflicts": n_conflict_cases,
        "prd_conflict_list": list(conflict_pairs.values()),
    }
