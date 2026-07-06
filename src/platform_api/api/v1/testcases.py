"""用例 API — 单条用例 review、详情查询、编辑、AI 重写"""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.celery_app import celery_app
from src.platform_api.core.database import get_session
from src.platform_api.core.response import success
from src.platform_api.schemas.testcase import RegenerateRequest, ReviewRequest, UpdateTestCaseRequest
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


@router.patch("/{case_id}")
async def update_testcase(
    case_id: UUID,
    body: UpdateTestCaseRequest,
    service: ReviewService = Depends(_get_review_service),
):
    """人工直接编辑用例"""
    data = body.model_dump(exclude_none=True)
    result = await service.update_case(case_id=case_id, data=data)
    return success(result)


@router.post("/{case_id}/regenerate", status_code=202)
async def regenerate_testcase(
    case_id: UUID,
    body: RegenerateRequest,
    service: ReviewService = Depends(_get_review_service),
):
    """单条 AI 按意见重写（异步 Celery）"""
    # 先验证用例存在
    await service.get_case_detail(case_id)

    celery_app.send_task(
        "testcase_generator.regenerate_case",
        kwargs={"case_id": str(case_id), "comment": body.comment},
        queue="testcase_generation",
    )
    return JSONResponse(
        status_code=202,
        content=success({"status": "regenerating", "case_id": str(case_id)}),
    )


@router.get("/{case_id}")
async def get_testcase(
    case_id: UUID,
    service: ReviewService = Depends(_get_review_service),
):
    """获取单条用例详情"""
    result = await service.get_case_detail(case_id)
    return success(result)
