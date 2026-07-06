"""通知 API — 未读数、消息列表、标记已读"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.schemas.notification import NotificationResponse, UnreadCountResponse, MarkAllReadResponse
from src.platform_api.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["通知管理"])


def _get_service(session: AsyncSession = Depends(get_session)) -> NotificationService:
    return NotificationService(session)


@router.get("/unread-count")
async def get_unread_count(
    service: NotificationService = Depends(_get_service),
):
    """获取未读通知消息数量"""
    count = await service.get_unread_count()
    return success(UnreadCountResponse(count=count).model_dump())


@router.get("")
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    is_read: bool | None = Query(None),
    service: NotificationService = Depends(_get_service),
):
    """分页获取通知消息列表"""
    items, total = await service.list_notifications(page=page, per_page=per_page, is_read=is_read)
    params = PaginationParams(page=page, per_page=per_page)

    # 序列化：使用 serialization_alias 输出 read 而非 is_read
    serialized_items = [NotificationResponse.model_validate(item).model_dump(by_alias=True) for item in items]

    return success(paginated_response(serialized_items, total, params))


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    service: NotificationService = Depends(_get_service),
):
    """标记单条通知为已读"""
    notification = await service.mark_read(notification_id)
    data = NotificationResponse.model_validate(notification).model_dump(by_alias=True)
    return success({"id": data["id"], "read": data["read"]})


@router.post("/mark-all-read")
async def mark_all_read(
    service: NotificationService = Depends(_get_service),
):
    """将所有未读通知标记为已读"""
    count = await service.mark_all_read()
    return success(MarkAllReadResponse(updated_count=count).model_dump())
