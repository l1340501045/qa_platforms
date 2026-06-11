"""章节性质分类 — 给每个 SectionExtract 标 section_kind，决定下游 oracle 策略。

用 LLM 分批分类（而非纯关键词），以区分"整章是 mock/二期"与"spec 章节夹一句 mock 脚注"。
失败 fail-open 为 spec（verify 关卡兜底）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List

from pydantic import BaseModel, Field

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.parsed_context import SectionExtract, SourceItem
from src.testcase_generator.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_VALID_KINDS = {"spec", "summary", "flow", "mock", "future", "tbd"}
_BATCH_SIZE = 20
_CONTENT_PREVIEW = 600

CLASSIFY_SYSTEM_PROMPT = """角色：你是需求文档分析员。任务：判断每个章节的"性质"，决定它能否作为测试用例预期结果（oracle）的依据。

把每个章节归为下列之一：
- spec：可验证规范——有明确字段/数值/状态机/枚举/文案/校验规则，能据此写确定的预期结果。
- summary：汇总或索引——目录、章节聚合、字段约束汇总表，本身不单独定义某个功能的行为。
- flow：流程图/示意——主要是流程图、时序、端到端示意（常只有节点名+一句话），不含后端机制细节。
- mock：本期模拟/未实现——明文写明"接口模拟 / mock / 当前 UI 未实现 / 未接接口 / 占位提示"，即本期不真正实现该行为。
- future：二期/规划——明文写明"二期 / v2.0 / 后续接入 / 规划支持 / 暂不做"等留待后续。
- tbd：待拍板/待确认——明文"待确认 / 待拍板 / 待定 / TBD"等尚未定方案。

判定要点：
- 看章节的【主体性质】，不要被一句附带脚注带偏。例如某章节整体是详细规范、只在末尾提一句"授权现行 Mock"，仍应判 spec（mock 只是其中一个子点）。
- 只有当【整章】的核心行为本期不实现/留二期/待定/仅是流程图时，才判 mock/future/tbd/flow。
- 拿不准时判 spec。

输出：严格按 JSON Schema，对输入每个章节给一条 {section_ref, kind}。"""


class _SectionKindOut(BaseModel):
    section_ref: str = Field(description="回填输入的 section_ref")
    kind: str = Field(description="spec/summary/flow/mock/future/tbd")


class _ClassifyOutput(BaseModel):
    classifications: List[_SectionKindOut] = Field(description="每个章节的分类")


def _split(items: list, size: int) -> list[list]:
    if len(items) <= size:
        return [items] if items else []
    return [items[i : i + size] for i in range(0, len(items), size)]


async def classify_sections(sources: list[SourceItem]) -> None:
    """原地给每个 section 标 section_kind（按章节批量，失败保留默认 spec）。"""
    # 收集 (source_ref → section) 引用；source_ref 在批内做键
    all_sections: list[SectionExtract] = []
    for src in sources:
        all_sections.extend(src.sections)
    if not all_sections:
        return

    by_ref: dict[str, SectionExtract] = {s.source_ref: s for s in all_sections}
    semaphore = asyncio.Semaphore(settings.llm_concurrency)

    async def _classify_batch(batch: list[SectionExtract]) -> None:
        payload = [
            {"section_ref": s.source_ref, "heading": s.heading, "content_preview": s.content[:_CONTENT_PREVIEW]}
            for s in batch
        ]
        async with semaphore:
            try:
                out = await get_llm_client().generate_structured(
                    system_prompt=CLASSIFY_SYSTEM_PROMPT,
                    user_content=json.dumps({"sections": payload}, ensure_ascii=False, indent=2),
                    output_schema=_ClassifyOutput,
                    temperature=0.0,
                )
            except Exception as e:  # noqa: BLE001 — 失败 fail-open 为 spec
                logger.warning("section 分类失败（保留默认 spec），n=%d: %s", len(batch), e)
                return
            for c in out.classifications:
                kind = c.kind.strip().lower()
                sec = by_ref.get(c.section_ref)
                if sec is not None and kind in _VALID_KINDS:
                    sec.section_kind = kind  # type: ignore[assignment]

    await asyncio.gather(*[_classify_batch(b) for b in _split(all_sections, _BATCH_SIZE)])

    dist: dict[str, int] = {}
    for s in all_sections:
        dist[s.section_kind] = dist.get(s.section_kind, 0) + 1
    logger.info("section 分类完成: %s", dist)
