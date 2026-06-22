"""Review service — 用例审核状态流转 + 批次用例列表查询"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.enums import ReviewStatus
from src.platform_api.models.testcase import TestCase
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.testcase import TestCaseListResponse, TestCaseResponse

VALID_REVIEW_STATUSES = {s.value for s in ReviewStatus}


class ReviewService:
    """用例 Review 服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BaseRepository(session, TestCase)

    async def review_case(self, case_id: UUID, status: str, comment: str | None) -> TestCaseResponse:
        """单条 review（状态流转）"""
        if status not in VALID_REVIEW_STATUSES:
            raise ApiError("E4001", f"无效的 review 状态，允许值：{list(VALID_REVIEW_STATUSES)}")

        case = await self.repo.get_by_id(case_id)
        if case is None:
            raise ApiError("E4041", "用例不存在")

        case.review_status = status
        case.review_comment = comment
        await self.session.flush()
        await self.session.refresh(case)

        return TestCaseResponse.model_validate(case)

    async def update_case(self, case_id: UUID, data: dict) -> TestCaseResponse:
        """人工编辑用例（只更新传入的非 None 字段）"""
        case = await self.repo.get_by_id(case_id)
        if case is None:
            raise ApiError("E4041", "用例不存在")

        editable_fields = {"title", "preconditions", "steps", "expected_results", "priority"}
        for field, value in data.items():
            if field in editable_fields and value is not None:
                setattr(case, field, value)

        await self.session.flush()
        await self.session.refresh(case)
        return TestCaseResponse.model_validate(case)

    async def get_case_detail(self, case_id: UUID) -> TestCaseResponse:
        """获取单条用例详情"""
        case = await self.repo.get_by_id(case_id)
        if case is None:
            raise ApiError("E4041", "用例不存在")
        return TestCaseResponse.model_validate(case)

    async def get_cases_by_batch(
        self, batch_id: UUID, review_status: str | None = None, offset: int = 0, limit: int = 50
    ) -> TestCaseListResponse:
        """获取批次用例列表（支持按 review_status 过滤）"""
        filters = [TestCase.batch_id == batch_id]
        if review_status:
            filters.append(TestCase.review_status == review_status)

        # 查询列表
        stmt = select(TestCase).where(*filters).order_by(TestCase.created_at.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        # 查询总数
        count_stmt = select(func.count()).select_from(TestCase).where(*filters)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        return TestCaseListResponse(
            items=[TestCaseResponse.model_validate(item) for item in items],
            total=total,
        )
