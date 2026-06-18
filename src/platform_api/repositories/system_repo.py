"""系统仓库 — 系统选项查询"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.public import System
from src.platform_api.repositories.base import BaseRepository


class SystemRepository(BaseRepository[System]):
    """系统数据仓库"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, System)

    async def find_options(self) -> list[dict]:
        """
        获取系统选项列表（id + name）

        用于前端系统下拉选择器。
        """
        stmt = select(System.id, System.name).order_by(System.name)
        result = await self.session.execute(stmt)
        return [row._asdict() for row in result.all()]
