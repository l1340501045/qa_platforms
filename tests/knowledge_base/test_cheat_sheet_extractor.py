"""cheat sheet 提取器测试：从实体图谱提取 4 类 QA 避坑条目。"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.knowledge_base.services.cheat_sheet.extractor import CheatSheetExtractorService
from src.platform_api.models.enums import CheatSheetType


def _entity(
    *,
    name: str,
    canonical_key: str,
    entity_type: str,
    section_ref: str | None = None,
    description: str | None = None,
    source_quote: str | None = None,
):
    entity = MagicMock()
    entity.id = uuid4()
    entity.name = name
    entity.canonical_key = canonical_key
    entity.entity_type = entity_type
    entity.section_ref = section_ref
    entity.description = description
    entity.source_quote = source_quote
    return entity


def _relation(source, target, relation_type: str, *, note: str | None = None, source_quote: str | None = None):
    relation = MagicMock()
    relation.id = uuid4()
    relation.source_entity_id = source.id
    relation.target_entity_id = target.id
    relation.relation_type = relation_type
    relation.note = note
    relation.source_quote = source_quote
    return relation


@pytest.mark.asyncio
async def test_extract_builds_four_cheat_sheet_types_with_tier_and_sources():
    """从全量 entities/relations 提取 must_test/confusion/priority/prd_status。"""
    doc_id = uuid4()
    global_section = _entity(
        name="§5.0.3 全局字数规则",
        canonical_key="§5.0.3",
        entity_type="section",
        section_ref="§5.0.3",
    )
    local_section = _entity(
        name="§5.7.1 定向包名称",
        canonical_key="§5.7.1",
        entity_type="section",
        section_ref="§5.7.1",
    )
    field = _entity(
        name="定向包名",
        canonical_key="field_定向包名",
        entity_type="field",
        section_ref="§5.7.1",
        description="定向包名 20 字符，支持 emoji",
        source_quote="定向包名字符不限含 emoji",
    )
    rule = _entity(
        name="定向包名称规则",
        canonical_key="rule_target_name",
        entity_type="rule",
        section_ref="§5.7.1",
        description="定向包名不按半角 0.5 字算法计算",
        source_quote="定向包名按 20 字符计算",
    )
    monitor_link = _entity(
        name="监测链接",
        canonical_key="concept_monitor_link",
        entity_type="concept",
        section_ref="§5.4",
    )
    delivery_link = _entity(
        name="投放链接",
        canonical_key="concept_delivery_link",
        entity_type="concept",
        section_ref="§5.4",
    )
    key_behavior = _entity(
        name="关键行为",
        canonical_key="concept_key_behavior",
        entity_type="concept",
        section_ref="§5.8",
    )
    delivery_type = _entity(
        name="投放方式",
        canonical_key="concept_delivery_type",
        entity_type="concept",
        section_ref="§5.8",
    )
    draft = _entity(name="草稿", canonical_key="state_draft", entity_type="state", section_ref="§6.1")
    submitted = _entity(name="已提交", canonical_key="state_submitted", entity_type="state", section_ref="§6.1")

    rule_constrains = _relation(rule, field, "rule_constrains", note="规则约束定向包名")
    field_defined = _relation(field, local_section, "field_defined_in", note="字段定义章节")
    confusion = _relation(
        monitor_link,
        delivery_link,
        "mutually_exclusive",
        note="监测链接用于归因，投放链接用于投放",
        source_quote="监测链接与投放链接不可混用",
    )
    priority = _relation(
        local_section,
        global_section,
        "section_priority",
        note="定向包名称局部规则优先全局字数规则",
        source_quote="本节字段以本节规则为准",
    )
    unreachable = _relation(
        key_behavior,
        delivery_type,
        "unreachable",
        note="关键行为不是投放方式，不应生成确定枚举",
        source_quote="关键行为待确认",
    )
    transition = _relation(draft, submitted, "transitions_to", note="提交后进入已提交状态")

    repo = AsyncMock()
    repo.get_entities_by_document = AsyncMock(
        return_value=[
            global_section,
            local_section,
            field,
            rule,
            monitor_link,
            delivery_link,
            key_behavior,
            delivery_type,
            draft,
            submitted,
        ]
    )
    repo.get_relations_by_document = AsyncMock(
        return_value=[rule_constrains, field_defined, confusion, priority, unreachable, transition]
    )
    service = CheatSheetExtractorService(repo)

    items = await service.extract(
        doc_id,
        section_statuses=[
            {
                "section_ref": "§8.4",
                "kind": "tbd",
                "heading": "文案配置",
                "annotation": "文案待确认，不可编造 oracle",
            }
        ],
    )

    by_type = {sheet_type: [item for item in items if item.sheet_type == sheet_type] for sheet_type in CheatSheetType}
    assert len(by_type[CheatSheetType.MUST_TEST]) == 1
    assert len(by_type[CheatSheetType.CONFUSION_PAIR]) == 1
    assert len(by_type[CheatSheetType.SECTION_PRIORITY]) == 1
    assert len(by_type[CheatSheetType.PRD_STATUS]) == 3

    must_test = by_type[CheatSheetType.MUST_TEST][0]
    assert must_test.review_tier == "sample"
    assert must_test.ai_content["rule_text"] == "定向包名不按半角 0.5 字算法计算"
    assert must_test.ai_content["applies_to"] == "定向包名"
    assert must_test.ai_content["section_ref"] == "§5.7.1"
    assert str(rule.id) in must_test.source_entity_ids
    assert str(rule_constrains.id) in must_test.source_relation_ids

    confusion_item = by_type[CheatSheetType.CONFUSION_PAIR][0]
    assert confusion_item.review_tier == "must"
    assert confusion_item.ai_content["item_a"] == "监测链接"
    assert confusion_item.ai_content["item_b"] == "投放链接"
    assert confusion_item.ai_content["distinction"] == "监测链接用于归因，投放链接用于投放"
    assert confusion_item.source_section_refs == ["§5.4"]

    priority_item = by_type[CheatSheetType.SECTION_PRIORITY][0]
    assert priority_item.review_tier == "must"
    assert priority_item.ai_content["local_section"] == "§5.7.1 定向包名称"
    assert priority_item.ai_content["global_section"] == "§5.0.3 全局字数规则"
    assert "局部规则优先" in priority_item.ai_content["resolution"]

    prd_status_kinds = {item.ai_content["status_kind"] for item in by_type[CheatSheetType.PRD_STATUS]}
    assert prd_status_kinds == {"unreachable", "transition", "tbd"}
    unreachable_item = next(
        item for item in by_type[CheatSheetType.PRD_STATUS] if item.ai_content["status_kind"] == "unreachable"
    )
    assert unreachable_item.review_tier == "must"
    assert unreachable_item.ai_content["subject"] == "关键行为"
    assert unreachable_item.ai_content["context"] == "投放方式"
    assert str(unreachable.id) in unreachable_item.source_relation_ids

    repo.get_entities_by_document.assert_awaited_once_with(doc_id)
    repo.get_relations_by_document.assert_awaited_once_with(doc_id)
