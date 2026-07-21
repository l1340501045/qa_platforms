"""Review service — 用例审核状态流转 + 批次用例列表查询"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.enums import ReviewStatus
from src.platform_api.models.testcase import TestBatch, TestCase
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.testcase import TestCaseListResponse, TestCaseResponse

VALID_REVIEW_STATUSES = {s.value for s in ReviewStatus}


async def lock_case_for_content_mutation(session: AsyncSession, case_id: UUID) -> TestCase:
    """按 batch→case 的固定顺序加锁，并拒绝修改已固化 taxonomy 的用例内容。"""
    batch_id = await session.scalar(select(TestCase.batch_id).where(TestCase.id == case_id))
    if batch_id is None:
        raise ApiError("E4041", "用例不存在")

    batch = (
        await session.execute(select(TestBatch).where(TestBatch.id == batch_id).with_for_update())
    ).scalar_one_or_none()
    if batch is None:
        raise ApiError("E4041", "用例所属批次不存在")
    case = (
        await session.execute(
            select(TestCase).where(TestCase.id == case_id, TestCase.batch_id == batch.id).with_for_update()
        )
    ).scalar_one_or_none()
    if case is None:
        raise ApiError("E4091", "用例在编辑期间已发生变化，请刷新后重试")
    if batch.taxonomy_version_id is not None:
        raise ApiError("E4092", "该批次的业务分类已固化，不能再修改用例内容")
    return case


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

    async def update_case(self, case_id: UUID, data: dict[str, Any]) -> TestCaseResponse:
        """人工编辑用例（只更新传入的非 None 字段）"""
        case = await lock_case_for_content_mutation(self.session, case_id)

        editable_fields = {"title", "preconditions", "steps", "expected_results", "priority"}
        for field, value in data.items():
            if field in editable_fields and value is not None:
                setattr(case, field, value)

        await self.session.flush()
        await self.session.refresh(case)
        return TestCaseResponse.model_validate(case)

    async def ensure_case_content_mutable(self, case_id: UUID) -> TestCaseResponse:
        """在派发异步重写前做同一套冻结检查；worker 落库前仍会再次校验。"""
        case = await lock_case_for_content_mutation(self.session, case_id)
        return TestCaseResponse.model_validate(case)

    async def get_case_detail(self, case_id: UUID) -> TestCaseResponse:
        """获取单条用例详情"""
        case = await self.repo.get_by_id(case_id)
        if case is None:
            raise ApiError("E4041", "用例不存在")
        return TestCaseResponse.model_validate(case)

    async def get_cases_by_batch(
        self,
        batch_id: UUID,
        review_status: str | None = None,
        keyword: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> TestCaseListResponse:
        """获取批次用例列表（支持按 review_status 过滤 + 标题关键词模糊搜索）"""
        filters = [TestCase.batch_id == batch_id]
        if review_status:
            filters.append(TestCase.review_status == review_status)
        if keyword and keyword.strip():
            filters.append(TestCase.title.ilike(f"%{keyword.strip()}%"))

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
