"""搜索 API — 用例全局搜索"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.response import success
from src.platform_api.services.case_search_service import CaseSearchService

router = APIRouter(prefix="/cases", tags=["用例搜索"])


def _get_service(session: AsyncSession = Depends(get_session)) -> CaseSearchService:
    return CaseSearchService(session)


@router.get("/search")
async def search_cases(
    q: str = Query(..., min_length=1, max_length=200, description="搜索关键词"),
    system_id: UUID | None = Query(None, description="系统 ID 筛选"),
    priority: str | None = Query(None, description="优先级筛选"),
    review_status: str | None = Query(None, description="review 状态筛选"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: CaseSearchService = Depends(_get_service),
):
    """跨系统全局搜索用例（基于 pg_trgm 模糊匹配）"""
    items, total = await service.search_cases(
        query=q,
        system_id=system_id,
        priority=priority,
        review_status=review_status,
        page=page,
        per_page=per_page,
    )

    total_pages = ceil(total / per_page) if per_page > 0 else 0

    return success(
        {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "query": q,
        }
    )
