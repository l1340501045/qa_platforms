"""通知 Service — 通知 CRUD 编排"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.repositories.notification_repo import NotificationRepository


class NotificationService:
    """通知管理逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = NotificationRepository(session)

    async def create_notification(
        self,
        type: str,
        title: str,
        body: str | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        actor: str = "system",
    ):
        """创建一条通知"""
        return await self.repo.create(
            type=type,
            title=title,
            body=body,
            target_type=target_type,
            target_id=target_id,
            actor=actor,
        )

    async def get_unread_count(self) -> int:
        """获取未读消息数"""
        return await self.repo.count_unread()

    async def list_notifications(
        self,
        page: int = 1,
        per_page: int = 20,
        is_read: bool | None = None,
    ) -> tuple[list, int]:
        """分页获取通知列表"""
        return await self.repo.find_all(page=page, per_page=per_page, is_read=is_read)

    async def mark_read(self, notification_id: UUID):
        """标记单条已读，返回更新后的通知"""
        notification = await self.repo.mark_read(notification_id)
        if notification is None:
            from src.platform_api.core.exceptions import ApiError

            raise ApiError("E4041", "通知不存在")
        return notification

    async def mark_all_read(self) -> int:
        """标记全部已读，返回受影响行数"""
        return await self.repo.mark_all_read()
