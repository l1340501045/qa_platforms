"""write_cases cheat sheet 注入过滤测试。"""

from uuid import uuid4

from src.knowledge_base.schemas.cheat_sheet import CheatSheetInjectionItem
from src.platform_api.models.enums import CheatSheetType
from src.testcase_generator.schemas.parsed_context import FeatureItem
from src.testcase_generator.stages.write_cases.cheat_sheet_inject import (
    filter_cheat_sheet_for_feature,
    format_cheat_sheet_for_prompt,
)


def _approved(
    *,
    sheet_type: CheatSheetType,
    title: str,
    content: dict,
    source_section_refs: list[str] | None = None,
) -> CheatSheetInjectionItem:
    return CheatSheetInjectionItem(
        id=uuid4(),
        sheet_type=sheet_type,
        title=title,
        content=content,
        review_tier="must",
        source_entity_ids=[],
        source_relation_ids=[],
        source_section_refs=source_section_refs or [],
    )


def test_filter_cheat_sheet_for_feature_matches_section_and_terms():
    """按 source_refs 与功能文本 token 过滤，只返回相关 approved 条目。"""
    feature = FeatureItem(
        id="F-023",
        name="漫剧选择与投放链接",
        description="批创页左栏选择漫剧后，需要按 IAP/IAA 投放链接和关键行为生成配置。",
        source_refs=["PRD §5.8.7"],
    )
    approved_by_type = {
        CheatSheetType.SECTION_PRIORITY: [
            _approved(
                sheet_type=CheatSheetType.SECTION_PRIORITY,
                title="章节优先：漫剧选择（左栏） > §5.8.7 选择商品",
                content={
                    "local_section": "漫剧选择（左栏）",
                    "global_section": "§5.8.7 选择商品",
                    "resolution": "切换漫剧时商品区搜索框重置逻辑参见§5.8.7的具体定义",
                },
                source_section_refs=["§5.8.7"],
            )
        ],
        CheatSheetType.CONFUSION_PAIR: [
            _approved(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="易混：IAP vs IAA",
                content={"item_a": "IAP", "item_b": "IAA", "distinction": "两种变现链路互斥"},
            )
        ],
        CheatSheetType.PRD_STATUS: [
            _approved(
                sheet_type=CheatSheetType.PRD_STATUS,
                title="不可达/待确认：关键行为 @ 投放方式",
                content={
                    "status_kind": "unreachable",
                    "subject": "关键行为",
                    "context": "投放方式",
                    "annotation": "关键行为不是投放方式",
                },
                source_section_refs=["§5.8"],
            )
        ],
        CheatSheetType.MUST_TEST: [
            _approved(
                sheet_type=CheatSheetType.MUST_TEST,
                title="必测：项目名 - 半角字符按0.5字计算",
                content={"rule_text": "项目名半角字符按0.5字计算", "applies_to": "项目名"},
                source_section_refs=["§5.0.3"],
            )
        ],
    }

    filtered = filter_cheat_sheet_for_feature(feature, approved_by_type)

    assert set(filtered.keys()) == {"confusion_pair", "section_priority", "prd_status"}
    assert filtered["confusion_pair"][0]["title"] == "易混：IAP vs IAA"
    assert filtered["section_priority"][0]["source_section_refs"] == ["§5.8.7"]
    assert filtered["prd_status"][0]["content"]["subject"] == "关键行为"
    assert "must_test" not in filtered


def test_format_cheat_sheet_for_prompt_is_compact_and_bounded():
    """格式化结果保持结构化、精简，单类型默认限制条数。"""
    feature = FeatureItem(
        id="F-001",
        name="IAP 链接",
        description="IAP 链接配置",
        source_refs=["PRD §1"],
    )
    approved_by_type = {
        CheatSheetType.CONFUSION_PAIR: [
            _approved(
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title=f"易混：IAP vs IAA #{idx}",
                content={"item_a": "IAP", "item_b": "IAA", "distinction": f"区别{idx}"},
            )
            for idx in range(10)
        ]
    }

    formatted = format_cheat_sheet_for_prompt(filter_cheat_sheet_for_feature(feature, approved_by_type), max_per_type=3)

    assert len(formatted["confusion_pair"]) == 3
    assert set(formatted["confusion_pair"][0].keys()) == {"title", "content", "source_section_refs"}
