"""T015: Stage 1 — parse 节点：文档解析 + 结构化上下文组装"""

from __future__ import annotations

import logging
import re
from collections import Counter
from uuid import UUID

from src.knowledge_base.schemas.common import RetrievalContext, SearchResult
from src.platform_api.core.settings import settings
from src.platform_api.models.enums import DocType
from src.testcase_generator.schemas.parsed_context import (
    FeatureItem,
    ParsedContext,
    PrototypeObservation,
    SectionExtract,
)
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.context_utils import _salient_terms
from src.testcase_generator.stages.parse.kb_retriever import (
    retrieve_entity_graph_hints,
    retrieve_knowledge_context,
)
from src.testcase_generator.stages.parse.mastergo_fetch import enrich_sections_with_mastergo
from src.testcase_generator.stages.parse.playwright_fetch import (
    PlaywrightConfig,
    fetch_prototype_observations,
)
from src.testcase_generator.stages.parse.feature_segmenter import decide_feature_roles
from src.testcase_generator.stages.parse.section_classifier import classify_sections
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
        # seed 文档即用户触发生成的目标文档，是本次生成的头号需求来源。
        is_seed = result.document_id == document_id
        doc_type = _infer_doc_type(result)
        # seed 文档若未能识别出类型（常见被误标/默认为 OTHER），按主需求文档（PRD）对待，
        # 避免可信度被压低；同时确保下面进入功能点提取分支。
        if is_seed and doc_type == DocType.OTHER:
            doc_type = DocType.PRD
        trust_level = _DOC_TYPE_TRUST.get(doc_type, 3)
        roles = None
        if settings.feature_seg_llm_enabled:
            roles = await decide_feature_roles(result.title, _parse_triples(result.content_snippet))
        sections = _extract_sections(result, doc_type, roles=roles or None)

        registry.register_source(
            doc_id=result.document_id,
            doc_type=doc_type,
            trust_level=trust_level,
            title=result.title,
            sections=sections,
        )

        # 3. 从主需求文档提取功能点：seed（无论类型）或 PRD 关联文档。
        #    seed 必须无条件提取，否则被误标类型的主文档会 features=0 → 0 测试点 → 0 用例。
        if is_seed or doc_type == DocType.PRD:
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

    # 落点⑦：MasterGo 原型规格接入（仅开关开且有 token；无链接/失败安全跳过）
    if settings.mastergo_enabled and settings.mastergo_api_token:
        await enrich_sections_with_mastergo(parsed_context.sources, settings.mastergo_api_token)

    # 5.5 章节性质分类（标 section_kind，供下游 oracle 策略 + verify 关卡使用）
    await classify_sections(parsed_context.sources)

    # 5.6 把 section_kind 透传给 feature（按 source_ref 反查），供 test_points 维度门控使用：
    #     summary/mock/future/tbd 章节不再机械全展 9 维度，避免 F-001 元章节、
    #     §9 字段汇总、§7.3 后续迭代等 PRD 性质章节产出无 oracle 占位用例。
    section_kind_by_ref: dict[str, str] = {}
    for src in parsed_context.sources:
        for sec in src.sections:
            section_kind_by_ref[sec.source_ref] = sec.section_kind
    for feat in parsed_context.features:
        for ref in feat.source_refs:
            kind = section_kind_by_ref.get(ref)
            if kind and kind != "spec":
                feat.section_kind = kind  # type: ignore[assignment]
                break

    # 5.7 实体图谱关系提示（entity_retrieval_enabled 开关控制）
    if settings.entity_retrieval_enabled:
        hints = await retrieve_entity_graph_hints(document_id, system_id)
        parsed_context.entity_graph_hints = hints

    logger.info(
        "parse_node complete: sources=%d, features=%d, prototype_obs=%d, entity_hints=%d",
        registry.count,
        len(features),
        len(prototype_observations) if prototype_observations else 0,
        len(parsed_context.entity_graph_hints),
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
    "变更记录",
    "修订说明",
    "修订记录",
    "修订历史",
    "修改记录",
    "更新记录",
    "版本历史",
    "版本记录",
    "评审记录",
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


# 同源二级章节合并(根因2:功能点过度切分)。
# 当一个一级功能下的多个二级章节其实是"同一功能的不同侧面"(功能说明/配置规则/
# 权限规则/原型),按二级粒度会把一个功能切成多个 feature，导致同样的场景跨 feature
# 重复出测试点与用例。判据：排除 meta 后的二级章节间存在足量「共享判别性术语」
# (出现在绝大多数二级章节中)，即视为同源 → 退回一级粒度合并。
# 大 PRD 的二级标题各讲不同功能、判别性术语几乎不共享 → 不触发(零回归)。
_COHESION_MIN_SHARED_TERMS = 4
_COHESION_MAX_SECTIONS = 8


def _second_level_cohesive(triples: list[tuple[int, str, str]]) -> bool:
    """各二级章节是否"同源"(同一功能的多侧面)：靠足量共享判别性术语判定。"""
    secs = [(h, b) for lv, h, b in triples if lv == 2 and not _is_meta_heading(h)]
    if not (3 <= len(secs) <= _COHESION_MAX_SECTIONS):
        return False
    term_sets: list[set[str]] = []
    for h, b in secs:
        terms = _salient_terms(f"{h}\n{b}")
        if len(terms) >= 3:  # 术语过少的章节视为噪声，不参与同源判定
            term_sets.append(terms)
    if len(term_sets) < 3:
        return False
    counter: Counter = Counter()
    for terms in term_sets:
        counter.update(terms)
    # 出现在「绝大多数」(≥ n-1)二级章节中的判别性术语视为共享核心术语
    need = max(2, len(term_sets) - 1)
    shared_core = sum(1 for _term, c in counter.items() if c >= need)
    return shared_core >= _COHESION_MIN_SHARED_TERMS


def _choose_feature_level(triples: list[tuple[int, str, str]]) -> int:
    """选定"功能模块"对应的标题层级：优先二级标题；无二级则退回一级。

    多数 PRD：# 文档标题 / ## 功能模块 / ###+ 模块细节。以二级标题为功能点粒度，
    把更深层级折叠进所属模块，既避免碎片化又保留完整上下文。

    例外(根因2)：当多个二级章节其实是"同一功能的多个侧面"(判别性术语高度共享)时，
    退回一级粒度合并成一个完整功能点，避免一个功能被切散、跨 feature 重复出测试点。
    """
    levels = [t[0] for t in triples]
    if sum(1 for lv in levels if lv == 2) >= 3:
        if _second_level_cohesive(triples):
            return 1
        return 2
    return 1


def _parse_triples(content: str) -> list[tuple[int, str, str]]:
    """从 Markdown 内容解析出 (level, heading, body) 三元组列表。"""
    if not content:
        return []
    parts = re.split(r"(?m)^(#{1,6})\s+(.+)$", content)
    if len(parts) <= 1:
        return []
    triples: list[tuple[int, str, str]] = []
    i = 1
    while i < len(parts) - 1:
        level = len(parts[i])
        heading = parts[i + 1].strip()
        body = (parts[i + 2] if i + 2 < len(parts) else "").strip()
        triples.append((level, heading, body))
        i += 3
    return triples


def _extract_sections(
    result: SearchResult, doc_type: str, *, roles: dict[int, str] | None = None
) -> list[SectionExtract]:
    """从 content_snippet 按"功能模块"粒度提取章节

    策略（硬约束：理解准确性 + 用例质量优先）：
    1. 以选定的 feature_level（通常二级标题）作为功能模块边界；
    2. 更深层级标题（子细节）折叠进所属模块的正文，保证单个功能点上下文完整；
    3. 命中非功能关键词（变更日志/背景/目标等）的标题及其整棵子树整体丢弃，
       避免对非功能段落生成无意义用例。

    当 roles 给定时，按 LLM 角色标注驱动边界判定（切分通用化）。
    """
    content = result.content_snippet
    if not content:
        return []

    triples = _parse_triples(content)
    if not triples:
        return [
            SectionExtract(
                heading=result.title,
                content=content.strip(),
                source_ref=f"{doc_type}:{result.title}",
            )
        ]

    sections: list[SectionExtract] = []
    current: dict | None = None
    skip_below_level: int | None = None

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

    if roles is None:
        # ── 旧路：死规则，行为逐字节等价 ──
        feature_level = _choose_feature_level(triples)

        for level, heading, body in triples:
            if skip_below_level is not None:
                if level > skip_below_level:
                    continue
                skip_below_level = None

            if _is_meta_heading(heading):
                _flush()
                skip_below_level = level
                continue

            if level <= feature_level:
                _flush()
                current = {"heading": heading, "content": body}
            else:
                if current is None:
                    current = {"heading": heading, "content": body}
                else:
                    current["content"] += f"\n\n{heading}\n{body}"
    else:
        # ── 新路：LLM 角色驱动 ──
        for i, (level, heading, body) in enumerate(triples):
            if skip_below_level is not None:
                if level > skip_below_level:
                    continue
                skip_below_level = None

            role = roles.get(i, "")

            if role in ("meta", "background"):
                _flush()
                skip_below_level = level
                continue

            if role == "feature_root":
                _flush()
                current = {"heading": heading, "content": body}
            elif role == "container":
                continue
            else:
                if current is None:
                    current = {"heading": heading, "content": body}
                else:
                    current["content"] += f"\n\n{heading}\n{body}"

    _flush()
    return sections


# 归一化 feature heading 用于同名合并（根因 P0-2：parse 把同 PRD 章节切成两个 feature
# 导致 F-012/F-013 灾难型重复）。剥掉中英章节号前缀、空白与全/半角标点差异，仅保留主体名。
_HEADING_NUM_PREFIX = re.compile(
    r"^[#\s§]*"  # 允许开头有 #、空白、§ 等
    r"(?:第\s*[一二三四五六七八九十百千零\d]+\s*[章节条款部分]?\s*[、,，.．:：\-—\s]*|"
    r"[一二三四五六七八九十百千零]+\s*[、,，.．:：\-—\s]+|"
    r"\d+(?:[.．]\d+)*[、,，.．:：\-—\s]*)"
)
_HEADING_LEADING_MARK = re.compile(r"^[#\s§]+")  # 兜底剥掉残留的 #/§/空白
_HEADING_PUNCT = re.compile(r"[\s\u3000\-_–—、,，.．:：;；()（）\[\]【】§]+")


def _normalize_heading(heading: str) -> str:
    """归一化章节标题为合并键：去章节号前缀、去标点空白、统一小写。"""
    if not heading:
        return ""
    h = _HEADING_LEADING_MARK.sub("", heading.strip())
    h = _HEADING_NUM_PREFIX.sub("", h)
    h = _HEADING_PUNCT.sub("", h).lower()
    return h


def _extract_features_from_sections(
    sections: list[SectionExtract],
    start_index: int,
) -> list[FeatureItem]:
    """从 PRD 章节中提取功能点。

    根因修复（P0-2）：相同归一化标题（去章节号 + 去标点空白后相等）的多个 section
    强制合并为一个 feature——避免 PRD 同名章节被切成两个 feature 导致下游测试点 ×2、
    用例 ×N 的"双 feature 灾难"（典例 F-012/F-013「六类投放方式字段对照」）。
    合并后 description 为各原 section 内容拼接，source_refs 累积。
    """
    features: list[FeatureItem] = []
    by_key: dict[str, FeatureItem] = {}

    for section in sections:
        if not section.content:
            continue
        key = _normalize_heading(section.heading)
        if key and key in by_key:
            existing = by_key[key]
            if section.content not in existing.description:
                existing.description = f"{existing.description}\n\n{section.content}"
            if section.source_ref not in existing.source_refs:
                existing.source_refs.append(section.source_ref)
            continue

        feature_id = f"F-{start_index + len(features) + 1:03d}"
        feature = FeatureItem(
            id=feature_id,
            name=section.heading,
            description=section.content,
            source_refs=[section.source_ref],
        )
        features.append(feature)
        if key:
            by_key[key] = feature

    return features
