"""章节性质分类 — 给每个 SectionExtract 标 section_kind + is_global，决定下游 oracle 策略与全局注入。

用 LLM 分批分类（而非纯关键词），以区分"整章是 mock/二期"与"spec 章节夹一句 mock 脚注"。
同时语义判定 is_global（是否适用于所有功能点的横切规则，落点⑧去领域绑定）。
失败 fail-open 为 spec / is_global=False（verify 关卡 + 关键词兜底）。
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
# 章节是「折叠后的整个功能模块」，深层 v1.0 规格常在中后部；预览过短会被开头的
# 「规划/二期」语气带偏，把整段误判 future/mock → write_cases 产出无 oracle 空壳
# （5b 复审 W17/F-022 §8.4 即此因）。放大预览窗，让分类看到段内的具体规格。
_CONTENT_PREVIEW = 2400

CLASSIFY_SYSTEM_PROMPT = """角色：你是需求文档分析员。
任务：判断每个章节的"性质"与"适用范围"，决定它能否作为测试用例预期结果（oracle）的依据、以及是否为全局规则。

一、把每个章节归为下列之一（kind）：
- spec：可验证规范——有明确字段/数值/状态机/枚举/文案/校验规则，能据此写确定的预期结果。
- summary：汇总或索引——目录、章节聚合、字段约束汇总表，本身不单独定义某个功能的行为。
- flow：流程图/示意——主要是流程图、时序、端到端示意（常只有节点名+一句话），不含后端机制细节。
- mock：本期模拟/未实现——明文写明"接口模拟 / mock / 当前 UI 未实现 / 未接接口 / 占位提示"，即本期不真正实现该行为。
- future：二期/规划——明文写明"二期 / v2.0 / 后续接入 / 规划支持 / 暂不做"等留待后续。
- tbd：待拍板/待确认——明文"待确认 / 待拍板 / 待定 / TBD"等尚未定方案。

判定要点：
- 看章节的【主体性质】，不要被一句附带脚注或开头一句话带偏。
  例如某章节开头写"本模块为后续规划"，但正文中后部给了具体字段/数值/状态机/校验规则，仍应判 spec。
- **只要段内任意位置含具体可验证规格**（字段定义、数值/枚举、状态机转移、校验规则、明文文案），
  即判 spec——哪怕标题或开头有"二期/规划/后续"字样。
- 只有当【整段核心行为】**都**属本期不实现/留二期/待定/仅是流程图（通篇找不到任何具体规格）时，
  才判 mock/future/tbd/flow。
- 拿不准时判 spec。误判 spec 的代价（多写几条可被 verify 关卡核验）远小于误判 future（整功能点覆盖坍塌）。

二、判断每个章节是否为「全局/横切规则」（is_global，布尔）：
- is_global=true：该章节定义的是**适用于所有/多个功能点**的通用规则——
  如全局交互约定（列表筛选/排序/分页通用规则）、贯穿多功能的公共字段/校验/约束、错误码、
  字数/计算规则、全局术语口径、多功能共用的机制说明等。它不专属于某一个功能点，应被所有功能点参考。
- is_global=false：该章节只描述**某一个具体功能点**自身的行为/界面/字段。
- 关键：判定看「规则的【适用范围】是否横跨多个功能」，**与具体业务领域无关**——
  不要依赖任何特定业务词，只看它是不是被多个功能点共用的通用规则。

输出：严格按 JSON Schema，对输入每个章节给一条 {section_ref, kind, is_global}。"""


class _SectionKindOut(BaseModel):
    section_ref: str = Field(description="回填输入的 section_ref")
    kind: str = Field(description="spec/summary/flow/mock/future/tbd")
    is_global: bool = Field(default=False, description="是否为适用于所有/多个功能点的全局·横切规则")


class _ClassifyOutput(BaseModel):
    classifications: List[_SectionKindOut] = Field(description="每个章节的分类")


def _split(items: list, size: int) -> list[list]:
    if len(items) <= size:
        return [items] if items else []
    return [items[i : i + size] for i in range(0, len(items), size)]


async def classify_sections(sources: list[SourceItem]) -> None:
    """原地给每个 section 标 section_kind + is_global（按章节批量，失败保留默认 spec / False）。"""
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
            except Exception as e:  # noqa: BLE001 — 失败 fail-open 为 spec / is_global=False
                logger.warning("section 分类失败（保留默认 spec），n=%d: %s", len(batch), e)
                return
            for c in out.classifications:
                sec = by_ref.get(c.section_ref)
                if sec is None:
                    continue
                kind = c.kind.strip().lower()
                if kind in _VALID_KINDS:
                    sec.section_kind = kind  # type: ignore[assignment]
                sec.is_global = bool(getattr(c, "is_global", False))

    await asyncio.gather(*[_classify_batch(b) for b in _split(all_sections, _BATCH_SIZE)])

    dist: dict[str, int] = {}
    for s in all_sections:
        dist[s.section_kind] = dist.get(s.section_kind, 0) + 1
    n_global = sum(1 for s in all_sections if s.is_global)
    logger.info("section 分类完成: %s, 全局横切=%d", dist, n_global)
