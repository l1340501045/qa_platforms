"""cheat sheet Repository — 文档级版本化存储 + 注入查询。"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.schemas.cheat_sheet import CheatSheetInjectionItem, CheatSheetItemCreate
from src.platform_api.models.enums import CheatSheetReviewStatus, CheatSheetType
from src.platform_api.models.knowledge import CheatSheet, CheatSheetItem


class CheatSheetRepository:
    """cheat sheet 版本化 CRUD。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_sheet(
        self,
        document_id: UUID,
        system_id: UUID,
        items: list[CheatSheetItemCreate],
        *,
        source_entity_count: int | None = None,
        source_relation_count: int | None = None,
    ) -> CheatSheet:
        """保存一次提取结果。

        每次 re-extract 都新建 version；若新条目能用 `(sheet_type, title)` 匹配旧 approved 条目，
        则继承 QA 内容和审核状态，避免 AI 重跑覆盖人工裁定。
        """
        previous_sheet = await self._get_latest_sheet(document_id)
        previous_approved = await self._get_previous_approved_by_key(previous_sheet.id) if previous_sheet else {}

        sheet = CheatSheet(
            id=uuid_mod.uuid4(),
            document_id=document_id,
            system_id=system_id,
            version=(previous_sheet.version + 1) if previous_sheet else 1,
            status="draft",
            source_entity_count=source_entity_count,
            source_relation_count=source_relation_count,
            extracted_at=datetime.now(UTC),
        )
        self.session.add(sheet)
        await self.session.flush()

        for item in items:
            previous_item = previous_approved.get((str(item.sheet_type), item.title))
            review_status = CheatSheetReviewStatus.PENDING
            qa_content = None
            review_comment = None
            reviewed_by = None
            reviewed_at = None
            if previous_item:
                review_status = CheatSheetReviewStatus.APPROVED
                qa_content = previous_item.qa_content
                review_comment = previous_item.review_comment
                reviewed_by = previous_item.reviewed_by
                reviewed_at = previous_item.reviewed_at

            self.session.add(
                CheatSheetItem(
                    id=uuid_mod.uuid4(),
                    sheet_id=sheet.id,
                    sheet_type=str(item.sheet_type),
                    title=item.title,
                    ai_content=item.ai_content,
                    qa_content=qa_content,
                    review_status=str(review_status),
                    review_tier=item.review_tier,
                    review_comment=review_comment,
                    reviewed_by=reviewed_by,
                    reviewed_at=reviewed_at,
                    source_entity_ids=item.source_entity_ids,
                    source_relation_ids=item.source_relation_ids,
                    source_section_refs=item.source_section_refs,
                    sort_order=item.sort_order,
                )
            )

        await self.session.flush()
        return sheet

    async def list_items(
        self,
        sheet_id: UUID,
        *,
        sheet_type: CheatSheetType | str | None = None,
        review_status: CheatSheetReviewStatus | str | None = None,
    ) -> list[CheatSheetItem]:
        """按 sheet 列表查询，支持类型/审核状态筛选。"""
        query = select(CheatSheetItem).where(CheatSheetItem.sheet_id == sheet_id)
        if sheet_type is not None:
            query = query.where(CheatSheetItem.sheet_type == str(sheet_type))
        if review_status is not None:
            query = query.where(CheatSheetItem.review_status == str(review_status))
        query = query.order_by(CheatSheetItem.sort_order.asc(), CheatSheetItem.created_at.asc())

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_approved_for_injection(
        self, document_id: UUID
    ) -> dict[CheatSheetType, list[CheatSheetInjectionItem]]:
        """返回最新 version 中 approved 条目，按类型分组。"""
        latest_sheet = await self._get_latest_sheet(document_id)
        if not latest_sheet:
            return {}

        items = await self.list_items(latest_sheet.id, review_status=CheatSheetReviewStatus.APPROVED)
        grouped: dict[CheatSheetType, list[CheatSheetInjectionItem]] = {}
        for item in items:
            sheet_type = CheatSheetType(item.sheet_type)
            grouped.setdefault(sheet_type, []).append(
                CheatSheetInjectionItem(
                    id=item.id,
                    sheet_type=sheet_type,
                    title=item.title,
                    content=item.qa_content or item.ai_content,
                    review_tier=item.review_tier,
                    source_entity_ids=item.source_entity_ids,
                    source_relation_ids=item.source_relation_ids,
                    source_section_refs=item.source_section_refs,
                    sort_order=item.sort_order,
                )
            )
        return grouped

    async def _get_latest_sheet(self, document_id: UUID) -> CheatSheet | None:
        result = await self.session.execute(
            select(CheatSheet)
            .where(CheatSheet.document_id == document_id)
            .order_by(CheatSheet.version.desc(), CheatSheet.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _get_previous_approved_by_key(self, sheet_id: UUID) -> dict[tuple[str, str], CheatSheetItem]:
        items = await self.list_items(sheet_id, review_status=CheatSheetReviewStatus.APPROVED)
        return {(item.sheet_type, item.title): item for item in items}
