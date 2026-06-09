"""用例 API — 单条用例 review 和详情查询"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.response import success
from src.platform_api.schemas.testcase import ReviewRequest
from src.platform_api.services.review_service import ReviewService

router = APIRouter(prefix="/testcases", tags=["用例管理"])


def _get_review_service(session: AsyncSession = Depends(get_session)) -> ReviewService:
    return ReviewService(session)


@router.patch("/{case_id}/review")
async def review_testcase(
    case_id: UUID,
    body: ReviewRequest,
    service: ReviewService = Depends(_get_review_service),
):
    """单条用例 review（状态流转）"""
    result = await service.review_case(
        case_id=case_id,
        status=body.status,
        comment=body.comment,
    )
    return success(result)


@router.get("/{case_id}")
async def get_testcase(
    case_id: UUID,
    service: ReviewService = Depends(_get_review_service),
):
    """获取单条用例详情"""
    result = await service.get_case_detail(case_id)
    return success(result)
