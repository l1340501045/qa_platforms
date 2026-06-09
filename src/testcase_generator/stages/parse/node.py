"""T015: Stage 1 — parse 节点：文档解析 + 结构化上下文组装"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from src.knowledge_base.schemas.common import RetrievalContext, SearchResult
from src.platform_api.models.enums import DocType
from src.testcase_generator.schemas.parsed_context import (
    FeatureItem,
    ParsedContext,
    PrototypeObservation,
    SectionExtract,
)
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.parse.kb_retriever import retrieve_knowledge_context
from src.testcase_generator.stages.parse.playwright_fetch import (
    PlaywrightConfig,
    fetch_prototype_observations,
)
from src.testcase_generator.stages.parse.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

# DocType → trust_level 映射
_DOC_TYPE_TRUST: dict[str, int] = {
    DocType.PRD: 1,
    DocType.TECH_DOC: 2,
    DocType.OTHER: 3,  # 用户口述/补充归为 level 3
    DocType.PROTOTYPE: 5,
    DocType.TEST_RULE: 2,
    DocType.TEST_CASE: 3,
    DocType.BUG_RECORD: 3,
}


async def parse_node(state: PipelineState) -> dict:
    """Stage 1: 解析需求文档 + 关联文档，构建结构化上下文

    流程：
    1. 从 KB 检索关联文档（进程内调用 RetrievalService，不传 query 不触发向量召回）
    2. 注册各文档到信源注册表（按 trust_level 排序）
    3. 解析各文档内容为 SectionExtract
    4. 从 PRD 文档中提取功能点（按 heading 拆分）
    5. 如有 prototype_links，通过 Playwright MCP 探索原型（trust_level=5）
    6. 返回 ParsedContext 写入 state
    """
    document_id = UUID(state["document_id"])
    system_id = UUID(state["system_id"])
    generation_config = state.get("generation_config", {})

    # 1. KB 检索（不传 query，只走关联图）
    retrieval_ctx: RetrievalContext = await retrieve_knowledge_context(
        document_id=document_id,
        system_id=system_id,
        max_depth=3,
    )

    # 2. 注册信源
    registry = SourceRegistry()
    features: list[FeatureItem] = []
    feature_counter = 0

    for result in retrieval_ctx.merged_results:
        doc_type = _infer_doc_type(result)
        trust_level = _DOC_TYPE_TRUST.get(doc_type, 3)
        sections = _extract_sections(result, doc_type)

        registry.register_source(
            doc_id=result.document_id,
            doc_type=doc_type,
            trust_level=trust_level,
            title=result.title,
            sections=sections,
        )

        # 3. 从 PRD 类文档提取功能点
        if doc_type == DocType.PRD:
            extracted = _extract_features_from_sections(sections, feature_counter)
            features.extend(extracted)
            feature_counter += len(extracted)

    # 4. 原型探索（可选）
    prototype_observations: list[PrototypeObservation] | None = None
    prototype_links = generation_config.get("prototype_links", [])
    if prototype_links:
        playwright_config = PlaywrightConfig(
            enabled=generation_config.get("playwright_enabled", False),
            endpoint=generation_config.get("playwright_endpoint", ""),
        )
        observations = await fetch_prototype_observations(
            prototype_links=prototype_links,
            config=playwright_config,
        )
        if observations:
            prototype_observations = observations

    # 5. 构建 ParsedContext
    parsed_context = ParsedContext(
        sources=registry.get_sorted_sources(),
        features=features,
        prototype_observations=prototype_observations,
    )

    logger.info(
        "parse_node complete: sources=%d, features=%d, prototype_obs=%d",
        registry.count,
        len(features),
        len(prototype_observations) if prototype_observations else 0,
    )

    return {
        "parsed_context": parsed_context,
        "current_stage": "parse",
    }


def _infer_doc_type(result: SearchResult) -> str:
    """从 SearchResult 推断文档类型"""
    # relation_type 可能暗示文档类型
    if result.relation_type:
        relation_to_type = {
            "req_to_tech": DocType.TECH_DOC,
            "req_to_case": DocType.TEST_CASE,
            "req_to_bug": DocType.BUG_RECORD,
            "req_to_proto": DocType.PROTOTYPE,
        }
        if result.relation_type in relation_to_type:
            return relation_to_type[result.relation_type]

    # 通过 title 启发式判断
    title_lower = result.title.lower() if result.title else ""
    if any(kw in title_lower for kw in ("prd", "需求", "requirement")):
        return DocType.PRD
    if any(kw in title_lower for kw in ("设计", "design", "技术", "tech")):
        return DocType.TECH_DOC
    if any(kw in title_lower for kw in ("原型", "prototype", "mock")):
        return DocType.PROTOTYPE

    return DocType.OTHER


# 非功能性章节关键词（命中则该标题及其子树不作为功能点，避免对"变更日志/背景"等生成无意义用例）
_META_HEADING_KEYWORDS = (
    "文档元信息",
    "文档版本",
    "变更日志",
    "修订说明",
    "修订记录",
    "版本历史",
    "需求背景",
    "预期目标",
    "需求概览",
    "术语",
    "名词解释",
    "附录",
    "参考文档",
    "目录",
    "changelog",
    "revision",
)


def _is_meta_heading(heading: str) -> bool:
    h = heading.lower()
    return any(kw.lower() in h for kw in _META_HEADING_KEYWORDS)


def _choose_feature_level(levels: list[int]) -> int:
    """选定"功能模块"对应的标题层级：优先二级标题；无二级则退回一级。

    多数 PRD：# 文档标题 / ## 功能模块 / ###+ 模块细节。以二级标题为功能点粒度，
    把更深层级折叠进所属模块，既避免碎片化又保留完整上下文。
    """
    if sum(1 for lv in levels if lv == 2) >= 3:
        return 2
    return 1


def _extract_sections(result: SearchResult, doc_type: str) -> list[SectionExtract]:
    """从 content_snippet 按"功能模块"粒度提取章节

    策略（硬约束：理解准确性 + 用例质量优先）：
    1. 以选定的 feature_level（通常二级标题）作为功能模块边界；
    2. 更深层级标题（子细节）折叠进所属模块的正文，保证单个功能点上下文完整；
    3. 命中非功能关键词（变更日志/背景/目标等）的标题及其整棵子树整体丢弃，
       避免对非功能段落生成无意义用例。
    """
    content = result.content_snippet
    if not content:
        return []

    parts = re.split(r"(?m)^(#{1,6})\s+(.+)$", content)
    if len(parts) <= 1:
        # 无 heading 结构，整体作为一个 section
        return [
            SectionExtract(
                heading=result.title,
                content=content.strip(),
                source_ref=f"{doc_type}:{result.title}",
            )
        ]

    # 解析成 (level, heading, body) 三元组
    triples: list[tuple[int, str, str]] = []
    i = 1
    while i < len(parts) - 1:
        level = len(parts[i])
        heading = parts[i + 1].strip()
        body = (parts[i + 2] if i + 2 < len(parts) else "").strip()
        triples.append((level, heading, body))
        i += 3

    feature_level = _choose_feature_level([t[0] for t in triples])

    sections: list[SectionExtract] = []
    current: dict | None = None
    skip_below_level: int | None = None  # 处于被丢弃的 meta 子树中时，记录其标题层级

    def _flush():
        nonlocal current
        if current and current["content"].strip():
            sections.append(
                SectionExtract(
                    heading=current["heading"],
                    content=current["content"].strip(),
                    source_ref=f"{doc_type}:{result.title} §{current['heading']}",
                )
            )
        current = None

    for level, heading, body in triples:
        # 1. meta 子树跳过：直到出现层级 <= meta 标题的标题才退出
        if skip_below_level is not None:
            if level > skip_below_level:
                continue
            skip_below_level = None

        # 2. 命中 meta 关键词：丢弃该标题及其整棵子树
        if _is_meta_heading(heading):
            _flush()
            skip_below_level = level
            continue

        if level <= feature_level:
            # 3. 新功能模块边界
            _flush()
            current = {"heading": heading, "content": body}
        else:
            # 4. 更深层级：折叠进当前模块，保留子标题作为结构标记
            if current is None:
                current = {"heading": heading, "content": body}
            else:
                current["content"] += f"\n\n{heading}\n{body}"

    _flush()
    return sections


def _extract_features_from_sections(
    sections: list[SectionExtract],
    start_index: int,
) -> list[FeatureItem]:
    """从 PRD 章节中提取功能点"""
    features: list[FeatureItem] = []

    for section in sections:
        if not section.content:
            continue
        feature_id = f"F-{start_index + len(features) + 1:03d}"
        features.append(
            FeatureItem(
                id=feature_id,
                name=section.heading,
                description=section.content,
                source_refs=[section.source_ref],
            )
        )

    return features
