"""批次列表 Service — 系统/文档级批次列表 + 导出选项"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.repositories.batch_repo import BatchRepository
from src.platform_api.repositories.system_repo import SystemRepository


class BatchListService:
    """批次列表查询编排"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.batch_repo = BatchRepository(session)
        self.system_repo = SystemRepository(session)

    async def list_by_system(
        self,
        system_id: UUID,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """获取系统下的批次列表"""
        return await self.batch_repo.find_by_system(system_id, status, page, per_page)

    async def list_by_document(
        self,
        document_id: UUID,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """获取文档下的批次列表"""
        return await self.batch_repo.find_by_document(document_id, status, page, per_page)

    async def list_batch_options(self) -> list[dict]:
        """获取可导出批次选项"""
        return await self.batch_repo.find_options()

    async def list_system_options(self) -> list[dict]:
        """获取系统选项"""
        return await self.system_repo.find_options()
