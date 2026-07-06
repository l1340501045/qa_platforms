"""实体关系抽取器 — 复用章节切分，LLM 并发抽取实体+关系，跨单元去重合并。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from src.knowledge_base.schemas.entity import EntityGraph, EntityItem

logger = logging.getLogger(__name__)

ENTITY_EXTRACT_SYSTEM_PROMPT = """你是 PRD 知识图谱构建专家。请从给定的 PRD 章节中抽取实体和关系。

实体类型：
- field: 具体字段（如"定向包名称"、"标题包名称"）
- section: 章节/模块（如"§5.7.1 定向包名称"）
- rule: 明确的业务规则（如"半角字符按 0.5 计算"）
- concept: 业务概念（如"监测链接"、"投放链接"）
- ui_element: UI 组件（如"创建按钮"、"分页器"）
- state: 状态/节点（如"草稿"、"已提交"、"已审核"）

关系类型（重点抽取 v5 痛点关系）：
- section_priority: 局部章节特例优先于全局规则（如 §5.7.1 优先 §5.0.3）
- field_defined_in: 字段定义在某章节
- rule_constrains: 规则约束某字段/实体
- mutually_exclusive: 两个概念/字段容易混淆但实际互斥（如"监测链接" vs "投放链接"）
- unreachable: 某概念/字段在特定上下文中不存在（如"关键行为"不是投放方式）
- belongs_to: 从属关系
- transitions_to: 状态转移（来自流程图/状态机）

规则：
- canonical_key 必须全局唯一且稳定（如用 §编号、field_中文名）
- 只抽 PRD 明确描述的事实，不推测
- 优先抽取"局部特例 vs 全局规则"、"易混概念"、"不存在项"这三类高价值关系"""


async def extract_entity_graph(
    *,
    units: list[dict],
    digest: str,
    generate_fn: Callable[..., Coroutine[Any, Any, EntityGraph]],
    concurrency: int = 4,
) -> EntityGraph:
    """从章节单元列表并发抽取实体图谱，跨单元按 canonical_key 去重合并。

    Args:
        units: build_units 产出的章节列表 [{title, level, chars, text}]
        digest: PRD 摘要（提供全局上下文）
        generate_fn: LLM 调用函数（兼容 LLMClient.generate_structured）
        concurrency: 并发度

    Returns:
        合并去重后的 EntityGraph
    """
    if not units:
        return EntityGraph(entities=[], relations=[])

    semaphore = asyncio.Semaphore(concurrency)
    unit_graphs: list[EntityGraph | None] = [None] * len(units)

    async def _extract_one(idx: int, unit: dict) -> None:
        async with semaphore:
            user_content = (
                f"【PRD 摘要】\n{digest}\n\n"
                f"【当前章节: {unit['title']}】\n{unit['text']}"
            )
            try:
                graph = await generate_fn(
                    system_prompt=ENTITY_EXTRACT_SYSTEM_PROMPT,
                    user_content=user_content,
                    output_schema=EntityGraph,
                )
                unit_graphs[idx] = graph
            except Exception as e:  # noqa: BLE001
                logger.error("实体抽取失败 unit=%s: %s", unit.get("title", idx), e)

    await asyncio.gather(*[_extract_one(i, u) for i, u in enumerate(units)])

    # 跨单元去重合并
    seen_keys: dict[str, EntityItem] = {}
    all_entities: list[EntityItem] = []
    all_relations = []

    for graph in unit_graphs:
        if graph is None:
            continue
        for entity in graph.entities:
            if entity.canonical_key not in seen_keys:
                seen_keys[entity.canonical_key] = entity
                all_entities.append(entity)
        all_relations.extend(graph.relations)

    return EntityGraph(entities=all_entities, relations=all_relations)
