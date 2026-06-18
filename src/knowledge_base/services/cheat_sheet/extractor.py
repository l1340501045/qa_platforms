"""从实体图谱提取 QA cheat sheet。"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from src.knowledge_base.repositories.cheat_sheet_repo import CheatSheetRepository
from src.knowledge_base.repositories.entity_repo import EntityRepository
from src.knowledge_base.schemas.cheat_sheet import CheatSheetItemCreate
from src.platform_api.models.enums import CheatSheetType, EntityRelationType, EntityType
from src.platform_api.models.knowledge import CheatSheet

_REVIEW_TIER_MUST = "must"
_REVIEW_TIER_SAMPLE = "sample"
_PRD_STATUS_KINDS = {"mock", "future", "tbd"}


class CheatSheetExtractorService:
    """把实体图谱关系提炼成 QA 可审核 cheat sheet 条目。"""

    def __init__(
        self,
        entity_repo: EntityRepository,
        *,
        cheat_sheet_repo: CheatSheetRepository | None = None,
    ):
        self.entity_repo = entity_repo
        self.cheat_sheet_repo = cheat_sheet_repo

    async def extract(
        self,
        document_id: UUID,
        *,
        section_statuses: list[dict] | None = None,
    ) -> list[CheatSheetItemCreate]:
        """从文档实体图谱提取 4 类 cheat sheet。"""
        entities = await self.entity_repo.get_entities_by_document(document_id)
        relations = await self.entity_repo.get_relations_by_document(document_id)
        return self._build_items(entities, relations, section_statuses or [])

    async def extract_and_save(
        self,
        document_id: UUID,
        system_id: UUID,
        *,
        section_statuses: list[dict] | None = None,
    ) -> CheatSheet:
        """提取并保存为新的 cheat sheet version。"""
        if self.cheat_sheet_repo is None:
            raise RuntimeError("cheat_sheet_repo is required for extract_and_save")

        entities = await self.entity_repo.get_entities_by_document(document_id)
        relations = await self.entity_repo.get_relations_by_document(document_id)
        items = self._build_items(entities, relations, section_statuses or [])

        return await self.cheat_sheet_repo.save_sheet(
            document_id,
            system_id,
            items,
            source_entity_count=len(entities),
            source_relation_count=len(relations),
        )

    def _build_items(
        self,
        entities: list,
        relations: list,
        section_statuses: list[dict],
    ) -> list[CheatSheetItemCreate]:
        """按固定顺序组装 4 类条目，并统一回填 sort_order。"""
        by_id = {entity.id: entity for entity in entities}
        items = [
            *self._extract_must_test(by_id, relations),
            *self._extract_confusion_pairs(by_id, relations),
            *self._extract_section_priority(by_id, relations),
            *self._extract_prd_status(by_id, relations, section_statuses or []),
        ]
        for index, item in enumerate(items):
            item.sort_order = index
        return items

    def _extract_must_test(self, by_id: dict, relations: list) -> list[CheatSheetItemCreate]:
        items: list[CheatSheetItemCreate] = []
        for relation in self._relations_of_type(relations, EntityRelationType.RULE_CONSTRAINS):
            rule = by_id.get(relation.source_entity_id)
            target = by_id.get(relation.target_entity_id)
            if not rule or not target or rule.entity_type != EntityType.RULE:
                continue

            defined_relation = self._find_field_defined_relation(target.id, relations)
            defined_section = by_id.get(defined_relation.target_entity_id) if defined_relation else None
            section_ref = target.section_ref or getattr(defined_section, "section_ref", None)

            source_entities = [rule, target]
            if defined_section:
                source_entities.append(defined_section)
            source_relations = [relation]
            if defined_relation:
                source_relations.append(defined_relation)

            rule_text = rule.description or rule.name
            items.append(
                CheatSheetItemCreate(
                    sheet_type=CheatSheetType.MUST_TEST,
                    title=f"必测：{target.name} - {rule.name}",
                    ai_content={
                        "rule_text": rule_text,
                        "category": target.entity_type,
                        "applies_to": target.name,
                        "section_ref": section_ref,
                        "source_quote": rule.source_quote or relation.source_quote,
                        "test_hint": relation.note or f"围绕「{target.name}」验证「{rule_text}」。",
                    },
                    review_tier=_REVIEW_TIER_SAMPLE,
                    source_entity_ids=self._entity_ids(source_entities),
                    source_relation_ids=self._relation_ids(source_relations),
                    source_section_refs=self._section_refs(source_entities),
                )
            )
        return items

    def _extract_confusion_pairs(self, by_id: dict, relations: list) -> list[CheatSheetItemCreate]:
        items: list[CheatSheetItemCreate] = []
        for relation in self._relations_of_type(relations, EntityRelationType.MUTUALLY_EXCLUSIVE):
            source = by_id.get(relation.source_entity_id)
            target = by_id.get(relation.target_entity_id)
            if not source or not target:
                continue
            items.append(
                CheatSheetItemCreate(
                    sheet_type=CheatSheetType.CONFUSION_PAIR,
                    title=f"易混：{source.name} vs {target.name}",
                    ai_content={
                        "item_a": source.name,
                        "item_b": target.name,
                        "distinction": relation.note,
                        "source_quote": relation.source_quote or source.source_quote or target.source_quote,
                    },
                    review_tier=_REVIEW_TIER_MUST,
                    source_entity_ids=self._entity_ids([source, target]),
                    source_relation_ids=self._relation_ids([relation]),
                    source_section_refs=self._section_refs([source, target]),
                )
            )
        return items

    def _extract_section_priority(self, by_id: dict, relations: list) -> list[CheatSheetItemCreate]:
        items: list[CheatSheetItemCreate] = []
        for relation in self._relations_of_type(relations, EntityRelationType.SECTION_PRIORITY):
            local_section = by_id.get(relation.source_entity_id)
            global_section = by_id.get(relation.target_entity_id)
            if not local_section or not global_section:
                continue
            items.append(
                CheatSheetItemCreate(
                    sheet_type=CheatSheetType.SECTION_PRIORITY,
                    title=f"章节优先：{local_section.name} > {global_section.name}",
                    ai_content={
                        "local_section": local_section.name,
                        "global_section": global_section.name,
                        "applies_when": relation.note,
                        "resolution": self._section_priority_resolution(local_section, global_section, relation.note),
                    },
                    review_tier=_REVIEW_TIER_MUST,
                    source_entity_ids=self._entity_ids([local_section, global_section]),
                    source_relation_ids=self._relation_ids([relation]),
                    source_section_refs=self._section_refs([local_section, global_section]),
                )
            )
        return items

    def _extract_prd_status(
        self,
        by_id: dict,
        relations: list,
        section_statuses: list[dict],
    ) -> list[CheatSheetItemCreate]:
        items: list[CheatSheetItemCreate] = []
        for relation in self._relations_of_type(relations, EntityRelationType.UNREACHABLE):
            source = by_id.get(relation.source_entity_id)
            target = by_id.get(relation.target_entity_id)
            if not source or not target:
                continue
            items.append(
                CheatSheetItemCreate(
                    sheet_type=CheatSheetType.PRD_STATUS,
                    title=f"不可达/待确认：{source.name} @ {target.name}",
                    ai_content={
                        "status_kind": "unreachable",
                        "subject": source.name,
                        "context": target.name,
                        "annotation": relation.note,
                        "source_quote": relation.source_quote or source.source_quote or target.source_quote,
                    },
                    review_tier=_REVIEW_TIER_MUST,
                    source_entity_ids=self._entity_ids([source, target]),
                    source_relation_ids=self._relation_ids([relation]),
                    source_section_refs=self._section_refs([source, target]),
                )
            )

        for relation in self._relations_of_type(relations, EntityRelationType.TRANSITIONS_TO):
            source = by_id.get(relation.source_entity_id)
            target = by_id.get(relation.target_entity_id)
            if not source or not target:
                continue
            items.append(
                CheatSheetItemCreate(
                    sheet_type=CheatSheetType.PRD_STATUS,
                    title=f"状态流转：{source.name} -> {target.name}",
                    ai_content={
                        "status_kind": "transition",
                        "subject": f"{source.name} -> {target.name}",
                        "context": source.section_ref or target.section_ref,
                        "annotation": relation.note,
                        "source_quote": relation.source_quote or source.source_quote or target.source_quote,
                    },
                    review_tier=_REVIEW_TIER_MUST,
                    source_entity_ids=self._entity_ids([source, target]),
                    source_relation_ids=self._relation_ids([relation]),
                    source_section_refs=self._section_refs([source, target]),
                )
            )

        for status in section_statuses:
            kind = str(status.get("kind", "")).lower()
            if kind not in _PRD_STATUS_KINDS:
                continue
            section_ref = status.get("section_ref")
            heading = status.get("heading") or section_ref or "未命名章节"
            items.append(
                CheatSheetItemCreate(
                    sheet_type=CheatSheetType.PRD_STATUS,
                    title=f"PRD状态：{heading}",
                    ai_content={
                        "status_kind": kind,
                        "subject": heading,
                        "context": section_ref,
                        "annotation": status.get("annotation") or f"章节标记为 {kind}，不可编造确定 oracle。",
                        "source_quote": status.get("source_quote"),
                    },
                    review_tier=_REVIEW_TIER_MUST,
                    source_entity_ids=[],
                    source_relation_ids=[],
                    source_section_refs=[section_ref] if section_ref else [],
                )
            )
        return items

    @staticmethod
    def _relations_of_type(relations: list, relation_type: EntityRelationType) -> Iterable:
        return (relation for relation in relations if relation.relation_type == relation_type)

    @staticmethod
    def _find_field_defined_relation(entity_id, relations: list):
        for relation in relations:
            if (
                relation.relation_type == EntityRelationType.FIELD_DEFINED_IN
                and relation.source_entity_id == entity_id
            ):
                return relation
        return None

    @staticmethod
    def _section_priority_resolution(local_section, global_section, note: str | None) -> str:
        note_text = note or ""
        neutral_markers = ("一致", "对齐", "统一", "无优先级差异")
        if any(marker in note_text for marker in neutral_markers):
            return f"「{local_section.name}」与「{global_section.name}」需按同一口径处理：{note_text}"
        return f"涉及「{local_section.name}」时，以局部规则优先，不能直接套用「{global_section.name}」。"

    @staticmethod
    def _entity_ids(entities: list) -> list[str]:
        return _dedupe([str(entity.id) for entity in entities if entity])

    @staticmethod
    def _relation_ids(relations: list) -> list[str]:
        return _dedupe([str(relation.id) for relation in relations if relation])

    @staticmethod
    def _section_refs(entities: list) -> list[str]:
        return _dedupe([entity.section_ref for entity in entities if entity and entity.section_ref])


def _dedupe(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
