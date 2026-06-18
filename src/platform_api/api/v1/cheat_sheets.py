"""cheat sheet API — ②a 极简提取触发入口。"""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.cheat_sheet_repo import CheatSheetRepository
from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.repositories.entity_repo import EntityRepository
from src.knowledge_base.services.cheat_sheet.extractor import CheatSheetExtractorService
from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.response import success
from src.platform_api.core.settings import settings

router = APIRouter(prefix="/documents", tags=["cheat sheet"])


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
