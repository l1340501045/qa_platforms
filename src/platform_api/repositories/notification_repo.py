"""通知仓库 — 通知 CRUD 操作"""

from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.public import Notification
from src.platform_api.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    """通知数据仓库"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Notification)

    async def count_unread(self) -> int:
        """统计未读消息数量"""
        stmt = select(func.count()).select_from(Notification).where(Notification.is_read == False)  # noqa: E712
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def find_all(
        self,
        page: int = 1,
        per_page: int = 20,
        is_read: bool | None = None,
    ) -> tuple[list[Notification], int]:
        """
        分页查询通知列表

        Returns:
            tuple[list[Notification], int]: (通知列表, 总数)
        """
        # 基础查询
        base_query = select(Notification)
        count_query = select(func.count()).select_from(Notification)

        # 已读状态筛选
        if is_read is not None:
            base_query = base_query.where(Notification.is_read == is_read)
            count_query = count_query.where(Notification.is_read == is_read)

        # 排序：最新消息在前
        base_query = base_query.order_by(Notification.created_at.desc())

        # 分页
        offset = (page - 1) * per_page
        base_query = base_query.offset(offset).limit(per_page)

        # 执行查询
        result = await self.session.execute(base_query)
        items = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def mark_read(self, notification_id: UUID) -> Notification | None:
        """
        标记单条通知为已读

        Returns:
            更新后的通知对象，不存在时返回 None
        """
        notification = await self.get_by_id(notification_id)
        if notification is None:
            return None

        notification.is_read = True
        await self.session.flush()
        await self.session.refresh(notification)
        return notification

    async def mark_all_read(self) -> int:
        """
        将所有未读通知标记为已读

        Returns:
            受影响的行数
        """
        stmt = (
            update(Notification)
            .where(Notification.is_read == False)  # noqa: E712
            .values(is_read=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount  # type: ignore[attr-defined]
