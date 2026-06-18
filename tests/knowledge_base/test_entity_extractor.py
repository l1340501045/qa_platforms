"""实体关系抽取器测试：复用章节切分 + 并发抽取 + 跨单元去重合并"""

import pytest

from src.knowledge_base.schemas.entity import EntityGraph, EntityItem, RelationItem
from src.knowledge_base.services.entity_graph.extractor import extract_entity_graph


def _unit(title: str, text: str) -> dict:
    return {"title": title, "level": 2, "chars": len(text), "text": text}


class TestExtractEntityGraph:
    @pytest.mark.asyncio
    async def test_basic_extraction(self):
        """fake client 返回实体+关系 → 正确产出 EntityGraph"""
        units = [
            _unit("§5.0.3 全局字数规则", "所有文本字段按半角 0.5 字算，上限 50 字"),
            _unit("§5.7.1 定向包名称", "定向包名称：字符不限含 emoji，按 20 字符算"),
        ]
        digest = "漫剧批创 PRD 摘要"

        call_count = {"n": 0}

        async def fake_generate(*, system_prompt, user_content, output_schema, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return EntityGraph(
                    entities=[
                        EntityItem(entity_type="section", name="全局字数规则", canonical_key="§5.0.3",
                                   section_ref="§5.0.3", description="所有字段半角 0.5 字算"),
                        EntityItem(entity_type="rule", name="半角0.5字算法", canonical_key="rule_half_width_0.5",
                                   section_ref="§5.0.3", description="半角字符按 0.5 计算"),
                    ],
                    relations=[],
                )
            else:
                return EntityGraph(
                    entities=[
                        EntityItem(entity_type="section", name="定向包名称", canonical_key="§5.7.1",
                                   section_ref="§5.7.1", description="字符不限含 emoji"),
                        EntityItem(entity_type="field", name="定向包名", canonical_key="field_定向包名",
                                   section_ref="§5.7.1", description="20 字符含 emoji"),
                    ],
                    relations=[
                        RelationItem(source_name="§5.7.1", target_name="§5.0.3",
                                     relation_type="section_priority", note="局部优先全局"),
                        RelationItem(source_name="field_定向包名", target_name="rule_half_width_0.5",
                                     relation_type="mutually_exclusive", note="定向包名不适用半角算法"),
                    ],
                )

        result = await extract_entity_graph(
            units=units, digest=digest, generate_fn=fake_generate, concurrency=2
        )

        assert isinstance(result, EntityGraph)
        assert len(result.entities) == 4
        assert len(result.relations) == 2

        keys = {e.canonical_key for e in result.entities}
        assert "§5.0.3" in keys
        assert "§5.7.1" in keys
        assert "field_定向包名" in keys

    @pytest.mark.asyncio
    async def test_cross_unit_dedup_by_canonical_key(self):
        """跨单元同 canonical_key 实体去重合并"""
        units = [
            _unit("§5.0 全局", "全局规则说明"),
            _unit("§5.7 定向", "引用全局规则"),
        ]

        async def dup_generate(*, system_prompt, user_content, output_schema, **kw):
            return EntityGraph(
                entities=[
                    EntityItem(entity_type="section", name="全局规则", canonical_key="§5.0.3",
                               section_ref="§5.0.3", description="全局"),
                ],
                relations=[],
            )

        result = await extract_entity_graph(
            units=units, digest="", generate_fn=dup_generate, concurrency=2
        )

        # 两个单元都抽出 §5.0.3 → 去重后只有 1 个
        assert len(result.entities) == 1
        assert result.entities[0].canonical_key == "§5.0.3"

    @pytest.mark.asyncio
    async def test_failure_isolation(self):
        """单单元抽取失败不影响其余"""
        units = [_unit(f"§{i}", f"章节{i}内容") for i in range(3)]
        call_count = {"n": 0}

        async def flaky(*, system_prompt, user_content, output_schema, **kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("LLM 超时")
            return EntityGraph(
                entities=[EntityItem(entity_type="concept", name=f"概念{call_count['n']}",
                                     canonical_key=f"c{call_count['n']}")],
                relations=[],
            )

        result = await extract_entity_graph(
            units=units, digest="", generate_fn=flaky, concurrency=1
        )

        # 第 2 个失败，只有 2 个实体
        assert len(result.entities) == 2

    @pytest.mark.asyncio
    async def test_empty_units_returns_empty_graph(self):
        """空输入 → 空图谱"""
        result = await extract_entity_graph(
            units=[], digest="", generate_fn=None, concurrency=2  # type: ignore
        )
        assert result.entities == []
        assert result.relations == []
