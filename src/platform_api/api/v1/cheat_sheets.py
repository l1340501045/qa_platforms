"""cheat sheet API — ②a 极简提取触发入口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.cheat_sheet_repo import CheatSheetRepository
from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.repositories.entity_repo import EntityRepository
from src.knowledge_base.services.cheat_sheet.extractor import CheatSheetExtractorService
from src.knowledge_base.services.cheat_sheet.review_service import CheatSheetReviewService
from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.core.settings import settings
from src.platform_api.models.enums import CheatSheetReviewStatus, CheatSheetType
from src.platform_api.models.knowledge import CheatSheet, CheatSheetItem
from src.platform_api.schemas.cheat_sheet import (
    CheatSheetBatchApproveRequest,
    CheatSheetEditRequest,
    CheatSheetReviewRequest,
)

router = APIRouter(prefix="/documents", tags=["cheat sheet"])
item_router = APIRouter(prefix="/cheat-sheets", tags=["cheat sheet"])


@router.post("/{document_id}/cheat-sheets/extract", status_code=202)
async def extract_cheat_sheets(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """手动触发某文档的 cheat sheet 提取。"""
    if not settings.cheat_sheet_extract_enabled:
        return JSONResponse(
            status_code=202,
            content=success(
                {
                    "enabled": False,
                    "message": "cheat_sheet_extract_enabled disabled",
                }
            ),
        )

    doc = await DocumentRepository(session).get_by_id(document_id)
    if doc is None:
        raise ApiError("E4041", "文档不存在")

    service = CheatSheetExtractorService(
        EntityRepository(session),
        cheat_sheet_repo=CheatSheetRepository(session),
    )
    sheet = await service.extract_and_save(document_id, doc.system_id)
    return JSONResponse(
        status_code=202,
        content=success(
            {
                "enabled": True,
                "sheet_id": str(sheet.id),
                "version": sheet.version,
            }
        ),
    )


@router.get("/{document_id}/cheat-sheets")
async def list_cheat_sheet_items(
    document_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sheet_type: CheatSheetType | None = Query(None, alias="type"),
    review_status: CheatSheetReviewStatus | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
):
    """列出某文档最新 cheat sheet version 的条目。"""
    latest_sheet = await _get_latest_sheet(session, document_id)
    params = PaginationParams(page=page, per_page=per_page)
    if latest_sheet is None:
        return success(paginated_response([], 0, params))

    filters = [CheatSheetItem.sheet_id == latest_sheet.id]
    if sheet_type is not None:
        filters.append(CheatSheetItem.sheet_type == str(sheet_type))
    if review_status is not None:
        filters.append(CheatSheetItem.review_status == str(review_status))

    total_result = await session.execute(select(func.count()).select_from(CheatSheetItem).where(*filters))
    total = total_result.scalar_one()
    result = await session.execute(
        select(CheatSheetItem)
        .where(*filters)
        .order_by(CheatSheetItem.sort_order.asc(), CheatSheetItem.created_at.asc())
        .offset(params.offset)
        .limit(params.limit)
    )
    items = [_serialize_item(item) for item in result.scalars().all()]
    return success(paginated_response(items, total, params))


@router.post("/{document_id}/cheat-sheets/batch-approve")
async def batch_approve_cheat_sheet_items(
    document_id: UUID,
    data: CheatSheetBatchApproveRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量通过某文档最新 cheat sheet version 的指定类型/档位。"""
    latest_sheet = await _get_latest_sheet(session, document_id)
    if latest_sheet is None:
        raise ApiError("E4041", "cheat sheet 不存在")

    updated_count = await CheatSheetReviewService(session).batch_approve(
        latest_sheet.id,
        sheet_type=data.sheet_type,
        tier=data.tier,
        by=data.by,
    )
    return success({"updated_count": updated_count})


@item_router.get("/{item_id}")
async def get_cheat_sheet_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """获取单条 cheat sheet 详情。"""
    item = await _get_item_or_404(session, item_id)
    return success(_serialize_item(item))


@item_router.patch("/{item_id}")
async def edit_cheat_sheet_item(
    item_id: UUID,
    data: CheatSheetEditRequest,
    session: AsyncSession = Depends(get_session),
):
    """编辑单条 cheat sheet 的 QA 版内容。"""
    try:
        item = await CheatSheetReviewService(session).edit(item_id, qa_content=data.qa_content)
    except ValueError as exc:
        raise ApiError("E4041", "cheat sheet 条目不存在") from exc
    return success(_serialize_item(item))


@item_router.patch("/{item_id}/review")
async def review_cheat_sheet_item(
    item_id: UUID,
    data: CheatSheetReviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """审核单条 cheat sheet。"""
    service = CheatSheetReviewService(session)
    try:
        if data.status == "approved":
            item = await service.approve(item_id, by=data.by)
        elif data.status == "rejected":
            item = await service.reject(item_id, comment=data.comment or "", by=data.by)
        else:
            raise ApiError("E4001", "status 必须为 approved 或 rejected")
    except ValueError as exc:
        raise ApiError("E4041", "cheat sheet 条目不存在") from exc
    return success(_serialize_item(item))


async def _get_latest_sheet(session: AsyncSession, document_id: UUID) -> CheatSheet | None:
    result = await session.execute(
        select(CheatSheet)
        .where(CheatSheet.document_id == document_id)
        .order_by(CheatSheet.version.desc(), CheatSheet.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _get_item_or_404(session: AsyncSession, item_id: UUID) -> CheatSheetItem:
    result = await session.execute(select(CheatSheetItem).where(CheatSheetItem.id == item_id))
    item = result.scalars().first()
    if item is None:
        raise ApiError("E4041", "cheat sheet 条目不存在")
    return item


def _serialize_item(item: CheatSheetItem) -> dict:
    return {
        "id": str(item.id),
        "sheet_id": str(item.sheet_id),
        "sheet_type": str(item.sheet_type),
        "title": item.title,
        "dedup_key": item.dedup_key,
        "ai_content": item.ai_content,
        "qa_content": item.qa_content,
        "review_status": str(item.review_status),
        "review_tier": item.review_tier,
        "review_comment": item.review_comment,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "source_entity_ids": item.source_entity_ids,
        "source_relation_ids": item.source_relation_ids,
        "source_section_refs": item.source_section_refs,
        "sort_order": item.sort_order,
    }
