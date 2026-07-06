"""cheat sheet 审核状态机。"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.enums import CheatSheetReviewStatus, CheatSheetType
from src.platform_api.models.knowledge import CheatSheetItem


class CheatSheetReviewService:
    """QA 审核/编辑 cheat sheet 条目。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def approve(self, item_id: UUID, *, by: str) -> CheatSheetItem:
        """审核通过单条 cheat sheet。"""
        item = await self._get_item(item_id)
        item.review_status = CheatSheetReviewStatus.APPROVED
        item.reviewed_by = by
        item.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        return item

    async def reject(self, item_id: UUID, *, comment: str, by: str) -> CheatSheetItem:
        """拒绝单条 cheat sheet。"""
        item = await self._get_item(item_id)
        item.review_status = CheatSheetReviewStatus.REJECTED
        item.review_comment = comment
        item.reviewed_by = by
        item.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        return item

    async def edit(self, item_id: UUID, *, qa_content: dict) -> CheatSheetItem:
        """编辑 QA 版内容；已审核/已拒绝条目编辑后转回 pending 等待复审。"""
        item = await self._get_item(item_id)
        item.qa_content = qa_content
        if item.review_status != CheatSheetReviewStatus.PENDING:
            item.review_status = CheatSheetReviewStatus.PENDING
            item.reviewed_by = None
            item.reviewed_at = None
        await self.session.flush()
        return item

    async def batch_approve(
        self,
        sheet_id: UUID,
        *,
        sheet_type: CheatSheetType | str,
        tier: str,
        by: str,
    ) -> int:
        """批量通过某类型/档位的 pending 条目。"""
        result = await self.session.execute(
            update(CheatSheetItem)
            .where(
                CheatSheetItem.sheet_id == sheet_id,
                CheatSheetItem.sheet_type == str(sheet_type),
                CheatSheetItem.review_tier == tier,
                CheatSheetItem.review_status == CheatSheetReviewStatus.PENDING,
            )
            .values(
                review_status=CheatSheetReviewStatus.APPROVED,
                reviewed_by=by,
                reviewed_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return result.rowcount or 0

    async def list_pending_must_review(self, sheet_id: UUID) -> list[CheatSheetItem]:
        """返回 QA 必审条目。"""
        result = await self.session.execute(
            select(CheatSheetItem)
            .where(
                CheatSheetItem.sheet_id == sheet_id,
                CheatSheetItem.review_tier == "must",
                CheatSheetItem.review_status == CheatSheetReviewStatus.PENDING,
            )
            .order_by(CheatSheetItem.sort_order.asc(), CheatSheetItem.created_at.asc())
        )
        return list(result.scalars().all())

    async def _get_item(self, item_id: UUID) -> CheatSheetItem:
        result = await self.session.execute(select(CheatSheetItem).where(CheatSheetItem.id == item_id))
        item = result.scalars().first()
        if item is None:
            raise ValueError(f"cheat sheet item not found: {item_id}")
        return item
