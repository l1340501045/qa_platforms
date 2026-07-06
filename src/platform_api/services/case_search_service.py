"""搜索 Service — 用例全局搜索"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.repositories.testcase_repo import TestCaseRepository


class CaseSearchService:
    """用例搜索逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TestCaseRepository(session)

    async def search_cases(
        self,
        query: str,
        system_id: UUID | None = None,
        priority: str | None = None,
        review_status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """
        搜索用例

        Args:
            query: 搜索关键词（已由 Router 层校验长度）
            system_id: 限定系统范围
            priority: 优先级筛选
            review_status: review 状态筛选
            page/per_page: 分页参数

        Returns:
            tuple[list[dict], int]: (搜索结果列表, 总数)
        """
        # 预处理：strip 空白
        query = query.strip()

        return await self.repo.search_by_text(
            query=query,
            system_id=system_id,
            priority=priority,
            review_status=review_status,
            page=page,
            per_page=per_page,
        )
